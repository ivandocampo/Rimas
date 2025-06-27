import argparse
import re
import sys
import logging
from collections import defaultdict
from io import BytesIO

import pandas as pd
import matplotlib.pyplot as plt

# Try importing pronunciation tools
try:
    import pronouncing
except ImportError:
    pronouncing = None

def is_streamlit():
    # Detecta si el script se está ejecutando bajo Streamlit
    return any('streamlit' in arg for arg in sys.argv)

USE_STREAMLIT = is_streamlit()
if USE_STREAMLIT:
    try:
        import streamlit as st
    except ImportError:
        raise ImportError("Para usar la interfaz GUI instala streamlit: pip install streamlit")

# Configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Core functionality ---

def get_rhyme_key(word, lang='es'):
    """
    Devuelve la clave de rima asonante de una palabra.
    - Para 'en', usa CMUdict (pronouncing).
    - Para otros idiomas (o fallback), usa reglas españolas.
    """
    w = word.lower()
    if lang == 'en' and pronouncing:
        phones = pronouncing.phones_for_word(w)
        if phones:
            phonemes = phones[0].split()
            stress_idxs = [i for i, p in enumerate(phonemes) if p[-1] in '12']
            idx = stress_idxs[-1] if stress_idxs else len(phonemes) - 1
            return ''.join(phonemes[idx:])
    # Fallback: reglas de español mejoradas
    orig = w
    trans = str.maketrans("áéíóúü", "aeiouu")
    norm = orig.translate(trans)
    # Extraer todas las vocales
    vocales = re.findall(r"[aeiou]", norm)
    # Usar las dos últimas vocales como clave de rima (o todas si hay menos)
    if not vocales:
        return ''
    clave = ''.join(vocales[-2:]) if len(vocales) >= 2 else vocales[0]
    return clave


def load_exceptions(path):
    """
    Carga una lista de palabras a excluir desde un TXT.
    """
    try:
        with open(path, encoding='utf-8') as f:
            return {line.strip().lower() for line in f if line.strip()}
    except Exception as e:
        logger.warning(f"No se pudo leer excepciones: {e}")
        return set()


def group_by_assonant_rhyme(text, exceptions=None, lang='es'):
    """
    Agrupa palabras por clave de rima, excluyendo excepciones y números.
    """
    if exceptions is None:
        exceptions = set()
    clean = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]", "", text)
    words = clean.split()
    groups = defaultdict(list)
    for w in words:
        lw = w.lower()
        if lw in exceptions:
            continue
        if lw.isdigit():
            continue  # Ignorar números
        key = get_rhyme_key(lw, lang)
        if key:
            groups[key].append(lw)
    return groups


def compute_stats(groups):
    """
    Calcula estadísticas de los grupos de rima.
    """
    sizes = [len(lst) for lst in groups.values()]
    total = len(groups)
    mean_size = sum(sizes) / total if total else 0
    max_size = max(sizes) if sizes else 0
    top10 = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    return {
        'total_groups': total,
        'mean_size': mean_size,
        'max_size': max_size,
        'top10': [(k, len(v)) for k, v in top10]
    }


def plot_group_distribution(groups):
    """
    Genera un histograma de tamaños de grupos y devuelve el fig.
    """
    sizes = [len(lst) for lst in groups.values()]
    fig, ax = plt.subplots()
    ax.hist(sizes, bins=range(1, max(sizes) + 2))
    ax.set_xlabel('Tamaño de grupo')
    ax.set_ylabel('Número de grupos')
    ax.set_title('Distribución de tamaños de grupos de rima')
    fig.tight_layout()
    return fig


def export_to_excel(df, stats, chart_fig, out_path):
    """
    Exporta DataFrame a Excel, con formato y hoja de estadísticas.
    """
    with pd.ExcelWriter(out_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Rimas', index=False)
        workbook = writer.book
        worksheet = writer.sheets['Rimas']
        worksheet.freeze_panes(1, 0)
        for i, col in enumerate(df.columns):
            max_len = max(df[col].astype(str).map(len).max(), len(col))
            worksheet.set_column(i, i, max_len + 2)
        stats_sheet = workbook.add_worksheet('Estadísticas')
        writer.sheets['Estadísticas'] = stats_sheet
        row = 0
        for k, v in stats.items():
            if k != 'top10':
                stats_sheet.write(row, 0, k)
                stats_sheet.write(row, 1, v)
                row += 1
        stats_sheet.write(row, 0, 'Top 10 claves')
        for i, (key, count) in enumerate(stats['top10'], start=row+1):
            stats_sheet.write(i, 0, key)
            stats_sheet.write(i, 1, count)
        chart_buf = BytesIO()
        chart_fig.savefig(chart_buf, format='png')
        stats_sheet.insert_image(row, 3, 'chart.png', {'image_data': BytesIO(chart_buf.getvalue())})


def save_words_to_db(words, db_path="palabras_db.csv"):
    """
    Guarda una lista de palabras en un CSV acumulativo.
    """
    import os
    import pandas as pd
    df_new = pd.DataFrame({"palabra": words})
    if os.path.exists(db_path):
        df_old = pd.read_csv(db_path)
        df_all = pd.concat([df_old, df_new], ignore_index=True)
        df_all.to_csv(db_path, index=False)
    else:
        df_new.to_csv(db_path, index=False)


# --- CLI Entry Point ---

def cli_main():
    p = argparse.ArgumentParser(
        description="Agrupa por rima, genera CSV/Excel y estadísticas."
    )
    p.add_argument('input_txt', help='Fichero .txt con la letra')
    p.add_argument('-e', '--exceptions', help='Fichero de excepciones')
    p.add_argument('-o', '--output_csv', default='rimas.csv', help='CSV de salida')
    p.add_argument('-x', '--output_excel', nargs='?', const='rimas.xlsx', help='Generar Excel con formato')
    p.add_argument('-l', '--lang', choices=['es', 'en'], default='es', help='Idioma: es o en')
    args = p.parse_args()

    try:
        with open(args.input_txt, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        logger.error(f"Error leyendo texto: {e}")
        sys.exit(1)
    exceptions = load_exceptions(args.exceptions) if args.exceptions else set()

    groups = group_by_assonant_rhyme(text, exceptions, lang=args.lang)
    if not groups:
        logger.warning("No se detectaron grupos de rima.")
    max_len = max((len(v) for v in groups.values()), default=0)
    data = {k: v + [''] * (max_len - len(v)) for k, v in groups.items()}
    df = pd.DataFrame(data)
    df.to_csv(args.output_csv, index=False, encoding='utf-8-sig')
    logger.info(f"CSV generado: {args.output_csv}")

    stats = compute_stats(groups)
    fig = plot_group_distribution(groups)
    if args.output_excel:
        export_to_excel(df, stats, fig, args.output_excel)
        logger.info(f"Excel generado: {args.output_excel}")


if __name__ == "__main__":
    if USE_STREAMLIT:
        pass  # No ejecutes CLI, Streamlit gestiona la ejecución
    else:
        cli_main()

# --- Streamlit GUI ---
if USE_STREAMLIT:
    st.title("Análisis de rimas asonantes")
    txt_file = st.file_uploader("Sube tu letra (.txt)", type='txt')
    exc_file = st.file_uploader("Sube excepciones (.txt)", type='txt')
    # --- Punto 7: Soporte para más idiomas ---
    lang = st.sidebar.selectbox('Idioma', ['es', 'en', 'fr', 'it'])
    # -----------------------------------------
    # --- Punto 8: Personalización de excepciones desde la interfaz ---
    st.sidebar.write("Palabras excluidas actuales:")
    exc_list = []
    if exc_file:
        exc_list = [l.strip().lower() for l in exc_file.read().decode('utf-8').splitlines() if l.strip()]
    exc_list = st.sidebar.text_area("Editar excepciones (una por línea)", value="\n".join(exc_list)).splitlines()
    exceptions = {l.strip().lower() for l in exc_list if l.strip()}
    # ----------------------------------------------------------------
    if txt_file:
        text = txt_file.read().decode('utf-8')
        groups = group_by_assonant_rhyme(text, exceptions, lang)
        # Guarda todas las palabras (sin excepciones ni números) en la base de datos
        all_words = [w for group in groups.values() for w in group]
        save_words_to_db(all_words)  # <-- Añade esta línea
        max_len = max((len(v) for v in groups.values()), default=0)
        data = {k: v + [''] * (max_len - len(v)) for k, v in groups.items()}
        df = pd.DataFrame(data)
        st.dataframe(df)

        # --- Selección de palabras a eliminar ---
        all_words = sorted({w for col in df.columns for w in df[col] if w})
        words_to_remove = st.multiselect("Palabras a eliminar", all_words)
        if words_to_remove:
            for col in df.columns:
                df[col] = df[col].apply(lambda x: "" if x in words_to_remove else x)
        # -----------------------------------------------

        # --- Punto 6: Gráfica de palabras más frecuentes ---
        from collections import Counter
        flat_words = [w for col in df.columns for w in df[col] if w]
        if flat_words:
            st.write("### Palabras más frecuentes")
            word_counts = Counter(flat_words)
            freq_df = pd.DataFrame(word_counts.most_common(15), columns=["Palabra", "Frecuencia"])
            st.bar_chart(freq_df.set_index("Palabra"))
        # ---------------------------------------------------

        stats = compute_stats({k: [w for w in v if w not in words_to_remove] for k, v in groups.items()} if words_to_remove else groups)
        st.write("## Estadísticas")
        st.json(stats)
        fig = plot_group_distribution({k: [w for w in v if w not in words_to_remove] for k, v in groups.items()} if words_to_remove else groups)
        st.pyplot(fig)
        towrite_excel = BytesIO()
        export_to_excel(df, stats, fig, towrite_excel)
        # --- Punto 1: Descarga directa del CSV ---
        towrite_csv = BytesIO()
        df.to_csv(towrite_csv, index=False, encoding='utf-8-sig')
        st.download_button("Descargar CSV", data=towrite_csv.getvalue(), file_name="rimas.csv", mime="text/csv")
        # -----------------------------------------
        st.download_button("Descargar Excel", data=towrite_excel.getvalue(), file_name="rimas.xlsx")