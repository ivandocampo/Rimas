import argparse
import re
import sys
import logging
import os
from collections import defaultdict
from io import BytesIO

import pandas as pd
import matplotlib.pyplot as plt

# Try importing pronunciation tools
try:
    import pronouncing
except ImportError:
    pronouncing = None

# Try importing Streamlit for GUI
try:
    import streamlit as st
    USE_STREAMLIT = True
except ImportError:
    USE_STREAMLIT = False

# Configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Core functionality ---

def get_rhyme_key(word, lang='es'):
    """
    Devuelve la clave de rima asonante de una palabra.
    - Para 'en', usa CMUdict (pronouncing).
    - Para otros idiomas, aplica reglas de español.
    """
    w = word.lower()
    if lang == 'en' and pronouncing:
        phones = pronouncing.phones_for_word(w)
        if phones:
            phonemes = phones[0].split()
            stress_idxs = [i for i, p in enumerate(phonemes) if p[-1] in '12']
            idx = stress_idxs[-1] if stress_idxs else len(phonemes) - 1
            return ''.join(phonemes[idx:])
    # Regla español fallback
    orig = w
    trans = str.maketrans("áéíóúü", "aeiouu")
    norm = orig.translate(trans)
    vowel_positions = [m.start() for m in re.finditer(r"[aeiou]", norm)]
    if not vowel_positions:
        return ''
    for i, ch in enumerate(orig):
        if ch in 'áéíóú':
            stress_idx = i
            break
    else:
        if orig[-1] in 'aeiouns':
            stress_idx = vowel_positions[-2] if len(vowel_positions) >= 2 else vowel_positions[-1]
        else:
            stress_idx = vowel_positions[-1]
    substring = norm[stress_idx:]
    return ''.join(re.findall(r"[aeiou]", substring))


def load_exceptions(path):
    """
    Carga lista de palabras a excluir desde un TXT.
    """
    try:
        with open(path, encoding='utf-8') as f:
            return {line.strip().lower() for line in f if line.strip()}
    except Exception as e:
        logger.warning(f"No se pudo leer excepciones: {e}")
        return set()


def process_file(path, exceptions, lang):
    """
    Procesa un archivo de letra (.txt), devuelve lista de registros.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    parts = [p.strip() for p in base.split(' - ', 1)]
    if len(parts) == 2:
        song, artist = parts
    else:
        song, artist = base, ''
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        logger.error(f"Error leyendo {path}: {e}")
        return []
    clean = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ]", "", text)
    words = clean.split()
    records = []
    for w in words:
        lw = w.lower()
        if lw in exceptions:
            continue
        key = get_rhyme_key(lw, lang)
        if key:
            records.append({'song': song, 'artist': artist,
                             'rhyme_key': key, 'word': lw})
    return records


def compute_stats(df):
    """
    Calcula estadísticas sobre el DataFrame combinado.
    """
    grp = df.groupby('rhyme_key')['word'].count()
    total = grp.size
    mean_size = grp.mean() if total else 0
    max_size = grp.max() if total else 0
    top10 = grp.sort_values(ascending=False).head(10).items()
    return {'total_groups': total,
            'mean_size': mean_size,
            'max_size': max_size,
            'top10': list(top10)}


def plot_group_distribution(df):
    """
    Histograma de tamaños de grupos combinados.
    """
    grp = df.groupby('rhyme_key')['word'].count()
    sizes = grp.values
    fig, ax = plt.subplots()
    ax.hist(sizes, bins=range(1, sizes.max() + 2))
    ax.set_xlabel('Tamaño de grupo')
    ax.set_ylabel('Número de grupos')
    ax.set_title('Distribución de tamaños de grupos de rima')
    fig.tight_layout()
    return fig


def export_to_excel(df, stats, fig, out_path):
    """
    Exporta a Excel: hoja 'Data', hoja 'Stats' con gráfico.
    """
    with pd.ExcelWriter(out_path, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Data', index=False)
        workbook = writer.book
        data_ws = writer.sheets['Data']
        data_ws.freeze_panes(1, 0)
        for i, col in enumerate(df.columns):
            width = max(df[col].astype(str).map(len).max(), len(col)) + 2
            data_ws.set_column(i, i, width)
        stats_ws = workbook.add_worksheet('Stats')
        writer.sheets['Stats'] = stats_ws
        row = 0
        for k, v in stats.items():
            if k != 'top10':
                stats_ws.write(row, 0, k)
                stats_ws.write(row, 1, v)
                row += 1
        stats_ws.write(row, 0, 'Top 10')
        for i, (key, count) in enumerate(stats['top10'], start=row+1):
            stats_ws.write(i, 0, key)
            stats_ws.write(i, 1, count)
        chart_buf = BytesIO()
        fig.savefig(chart_buf, format='png')
        stats_ws.insert_image(row, 3, 'chart.png', {'image_data': BytesIO(chart_buf.getvalue())})


# --- CLI Entry Point ---

def cli_main():
    p = argparse.ArgumentParser(
        description="Agrupa varios archivos por rima, genera un CSV/Excel y estadísticas."
    )
    p.add_argument('input_txts', nargs='+', help='Ficheros .txt con las letras')
    p.add_argument('-e', '--exceptions', help='Fichero de excepciones')
    p.add_argument('-o', '--output_csv', default='all_rimas.csv', help='CSV combinado de salida')
    p.add_argument('-x', '--output_excel', nargs='?', const='all_rimas.xlsx', help='Generar Excel combinado')
    p.add_argument('-l', '--lang', choices=['es', 'en'], default='es', help='Idioma: es o en')
    args = p.parse_args()

    exceptions = load_exceptions(args.exceptions) if args.exceptions else set()
    all_records = []
    for path in args.input_txts:
        all_records.extend(process_file(path, exceptions, lang=args.lang))
    if not all_records:
        logger.warning("No se detectaron registros.")
    df = pd.DataFrame(all_records)
    df.to_csv(args.output_csv, index=False, encoding='utf-8-sig')
    logger.info(f"CSV generado: {args.output_csv}")

    stats = compute_stats(df)
    fig = plot_group_distribution(df)
    if args.output_excel:
        export_to_excel(df, stats, fig, args.output_excel)
        logger.info(f"Excel generado: {args.output_excel}")


if __name__ == '__main__':
    if not USE_STREAMLIT:
        cli_main()

# --- Streamlit GUI ---
if USE_STREAMLIT:
    st.title("Análisis de rimas asonantes multiple")
    st.sidebar.header("Opciones")
    uploaded = st.file_uploader("Sube las letras (.txt)", type='txt', accept_multiple_files=True)
    exc_file = st.sidebar.file_uploader("Sube excepciones (.txt)", type='txt')
    lang = st.sidebar.selectbox('Idioma', ['es', 'en'])
    if uploaded:
        exceptions = set()
        if exc_file:
            exceptions = {l.strip().lower() for l in exc_file.read().decode('utf-8').splitlines() if l.strip()}
        all_records = []
        for up in uploaded:
            # Guardar temporalmente para usar process_file
            with open(up.name, 'wb') as tmp:
                tmp.write(up.read())
            all_records.extend(process_file(up.name, exceptions, lang))
        df = pd.DataFrame(all_records)
        if not df.empty:
            st.subheader("Datos de rimas")
            st.dataframe(df)
            # Estadísticas
            stats = compute_stats(df)
            st.subheader("Estadísticas")
            st.json(stats)
            fig = plot_group_distribution(df)
            st.pyplot(fig)
            # Descarga CSV y Excel
            csv_buf = BytesIO()
            df.to_csv(csv_buf, index=False, encoding='utf-8-sig')
            st.download_button("Descargar CSV", data=csv_buf.getvalue(), file_name="all_rimas.csv")
            excel_buf = BytesIO()
            export_to_excel(df, stats, fig, excel_buf)
            st.download_button("Descargar Excel", data=excel_buf.getvalue(), file_name="all_rimas.xlsx")
