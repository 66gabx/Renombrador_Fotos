"""Renombrador de Fotografías en Streamlit.

La aplicación recibe fotografías, prepara una vista previa y genera un ZIP
con los nombres nuevos. No modifica el contenido de los archivos originales.
"""

from datetime import datetime
from io import BytesIO
import hashlib
import os
from zipfile import ZIP_DEFLATED, ZipFile

import streamlit as st
from PIL import Image


EXTENSIONES_PERMITIDAS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".arw",
    ".nef",
    ".cr2",
    ".cr3",
    ".raf",
    ".dng",
    ".orf",
}


def obtener_fecha_captura(archivo):
    """Intenta leer DateTimeOriginal usando Pillow y EXIF estándar."""
    try:
        imagen = Image.open(BytesIO(archivo.getvalue()))
        exif = imagen.getexif()
        valor = exif.get(36867) or exif.get(306)

        if not valor:
            return None

        for formato in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(str(valor), formato)
            except ValueError:
                continue
    except (OSError, ValueError, KeyError):
        # Muchos formatos RAW no son legibles por Pillow sin complementos.
        return None

    return None


def ordenar_fotografias(archivos):
    """Ordena por captura si todos tienen fecha; si no, conserva el orden recibido."""
    archivos_con_fecha = []

    # Se conserva la posición original como criterio de estabilidad.
    for posicion, archivo in enumerate(archivos):
        fecha = obtener_fecha_captura(archivo)
        archivos_con_fecha.append((posicion, archivo, fecha))

    # Sin fecha fiable para todo el grupo no se inventa un orden alternativo.
    if any(fecha is None for _, _, fecha in archivos_con_fecha):
        return list(archivos), False

    archivos_ordenados = sorted(
        archivos_con_fecha,
        key=lambda elemento: elemento[2],
    )
    return [archivo for _, archivo, _ in archivos_ordenados], True


def crear_firma(archivos, texto, modalidad):
    """Crea una firma para invalidar vistas previas antiguas."""
    partes = [texto, modalidad]

    for archivo in archivos:
        contenido = archivo.getvalue()
        resumen = hashlib.sha256(contenido).hexdigest()
        partes.append(f"{archivo.name}:{resumen}")

    return "|".join(partes)


def preparar_cambios(archivos, texto, modalidad):
    """Prepara los nombres nuevos y detecta conflictos sin crear archivos."""
    archivos_a_procesar = list(archivos)
    orden_cronologico = False

    # Solo la modalidad completa necesita numeración y orden cronológico.
    if modalidad == "completo":
        archivos_a_procesar, orden_cronologico = ordenar_fotografias(archivos)

    nombres_originales = [archivo.name for archivo in archivos]
    destinos_preparados = set()
    cambios = []

    # El ciclo FOR hace visible el procesamiento secuencial de cada fotografía.
    for posicion, archivo in enumerate(archivos_a_procesar, start=1):
        nombre_original = os.path.basename(archivo.name)
        nombre_sin_extension, extension = os.path.splitext(nombre_original)

        if modalidad == "completo":
            nombre_nuevo = f"{texto}_{posicion}{extension}"
        else:
            nombre_nuevo = f"{nombre_sin_extension}_{texto}{extension}"

        problema = ""
        if nombre_nuevo in destinos_preparados:
            problema = "el destino se repite en la selección"
        elif nombre_nuevo in nombres_originales and nombre_nuevo != nombre_original:
            problema = "el destino coincide con otro archivo seleccionado"

        destinos_preparados.add(nombre_nuevo)
        cambios.append(
            {
                "archivo": archivo,
                "original": nombre_original,
                "nuevo": nombre_nuevo,
                "problema": problema,
            }
        )

    return cambios, orden_cronologico


def construir_zip(cambios):
    """Crea un ZIP en memoria con los archivos que no tienen conflicto."""
    datos_zip = BytesIO()
    renombradas = []
    no_modificadas = []

    with ZipFile(datos_zip, "w", ZIP_DEFLATED) as archivo_zip:
        nombres_incluidos = set()

        # Cada archivo se procesa por separado para continuar si ocurre un error.
        for cambio in cambios:
            nombre_original = cambio["original"]
            nombre_nuevo = cambio["nuevo"]
            problema = cambio["problema"]

            if problema:
                no_modificadas.append(
                    f"{nombre_original} → {nombre_nuevo}: {problema}"
                )
                continue

            # Segunda comprobación para impedir duplicados dentro del ZIP.
            if nombre_nuevo in nombres_incluidos:
                no_modificadas.append(
                    f"{nombre_original} → {nombre_nuevo}: el destino se repite"
                )
                continue

            try:
                archivo_zip.writestr(nombre_nuevo, cambio["archivo"].getvalue())
                nombres_incluidos.add(nombre_nuevo)
                renombradas.append(f"{nombre_original} → {nombre_nuevo}")
            except (OSError, ValueError, RuntimeError) as error:
                no_modificadas.append(
                    f"{nombre_original}: no se pudo incluir ({error})"
                )

    datos_zip.seek(0)
    return datos_zip.getvalue(), renombradas, no_modificadas


def mostrar_resumen(renombradas, no_modificadas):
    """Muestra el resultado del proceso en la interfaz."""
    st.subheader("Resumen")
    st.success(f"Fotografías preparadas: {len(renombradas)}")

    if renombradas:
        st.write("Archivos incluidos en el ZIP:")
        for elemento in renombradas:
            st.write(f"✅ {elemento}")

    if no_modificadas:
        st.warning(f"Fotografías no modificadas: {len(no_modificadas)}")
        for elemento in no_modificadas:
            st.write(f"⚠️ {elemento}")
    else:
        st.info("No hubo fotografías con conflictos o errores.")


def mostrar_vista_previa(cambios, orden_cronologico):
    """Muestra los nombres originales, nuevos y el estado de cada cambio."""
    st.subheader("Vista previa")

    if orden_cronologico:
        st.info("Orden aplicado: fecha de captura EXIF.")
    else:
        st.info(
            "No se pudo obtener una fecha de captura para todo el grupo; "
            "se conserva el orden de selección."
        )

    filas = []
    for cambio in cambios:
        estado = cambio["problema"] or "Listo"
        filas.append(
            {
                "Nombre original": cambio["original"],
                "Nombre nuevo": cambio["nuevo"],
                "Estado": estado,
            }
        )

    st.dataframe(filas, use_container_width=True, hide_index=True)


def main():
    """Construye la interfaz web y controla el flujo de la aplicación."""
    st.set_page_config(
        page_title="Renombrador de Fotografías",
        page_icon="📷",
        layout="wide",
    )

    st.title("📷 Renombrador de Fotografías")
    st.write(
        "Sube tus fotografías, prepara una vista previa y descarga un ZIP "
        "con los nombres nuevos. El contenido de las fotografías no se modifica."
    )

    archivos = st.file_uploader(
        "Seleccionar fotografías",
        accept_multiple_files=True,
    )
    texto = st.text_input("Nombre nuevo o texto final")

    if archivos:
        st.caption(f"Fotografías seleccionadas: {len(archivos)}")
    else:
        st.info("Selecciona una o más fotografías para comenzar.")

    # Los dos botones preparan modalidades diferentes sin renombrar todavía.
    columna_completa, columna_texto = st.columns(2)
    with columna_completa:
        boton_completo = st.button(
            "Renombrar por completo",
            use_container_width=True,
        )
    with columna_texto:
        boton_texto = st.button(
            "Añadir texto al final",
            use_container_width=True,
        )

    if boton_completo or boton_texto:
        if not archivos:
            st.warning("Primero debes seleccionar una o más fotografías.")
        elif not texto.strip():
            st.warning("Debes escribir un nombre nuevo o un texto final.")
        elif "/" in texto or "\\" in texto:
            st.warning("El texto no puede contener / ni la barra invertida (\\).")
        else:
            modalidad = "completo" if boton_completo else "anadir"
            cambios, orden_cronologico = preparar_cambios(
                archivos,
                texto.strip(),
                modalidad,
            )
            st.session_state.cambios_preparados = cambios
            st.session_state.modalidad_preparada = modalidad
            st.session_state.orden_cronologico = orden_cronologico
            st.session_state.firma_preparada = crear_firma(
                archivos,
                texto.strip(),
                modalidad,
            )
            st.session_state.resultado = None

    cambios_preparados = st.session_state.get("cambios_preparados", [])
    if cambios_preparados:
        mostrar_vista_previa(
            cambios_preparados,
            st.session_state.get("orden_cronologico", False),
        )

        modalidad_preparada = st.session_state.get("modalidad_preparada", "")
        firma_actual = crear_firma(
            archivos or [],
            texto.strip(),
            modalidad_preparada,
        )

        if firma_actual != st.session_state.get("firma_preparada"):
            st.warning(
                "La selección o el texto cambiaron. Prepara nuevamente la vista previa."
            )
        else:
            confirmar = st.checkbox(
                "Confirmo que deseo generar estos nombres y descargar el ZIP."
            )
            if st.button("Confirmar y generar ZIP", type="primary"):
                if not confirmar:
                    st.warning("Debes confirmar antes de generar el ZIP.")
                else:
                    datos_zip, renombradas, no_modificadas = construir_zip(
                        cambios_preparados
                    )
                    st.session_state.resultado = (
                        datos_zip,
                        renombradas,
                        no_modificadas,
                    )

    if st.session_state.get("resultado"):
        datos_zip, renombradas, no_modificadas = st.session_state.resultado
        mostrar_resumen(renombradas, no_modificadas)
        st.download_button(
            "Descargar fotografías renombradas (.zip)",
            data=datos_zip,
            file_name="fotografias_renombradas.zip",
            mime="application/zip",
            use_container_width=True,
        )

    st.caption(
        "Nota: en Streamlit Cloud los archivos subidos son temporales. "
        "La aplicación no puede modificar directamente archivos del computador."
    )


if __name__ == "__main__":
    if "cambios_preparados" not in st.session_state:
        st.session_state.cambios_preparados = []
    if "resultado" not in st.session_state:
        st.session_state.resultado = None
    main()
