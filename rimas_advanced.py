import re
import sys
import logging
import os
from collections import defaultdict
from io import BytesIO

import pandas as pd
import matplotlib.pyplot as plt

# Pronunciation support
try:
    import pronouncing
except ImportError:
    pronouncing = None

# Streamlit support
try:
    import streamlit as st
    USE_STREAMLIT = True
except ImportError:
    st = None
    USE_STREAMLIT = False

# Configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Core functions ---

def get_rhyme_key(word, lang='es'):
    w = word.lower()
    if lang == 'en' and pronouncing:
        phones = pronouncing.phones_for_word(w)
        if phones:
            phonemes = phones[0].split()
            stress = [i for i, p in enumerate(phonemes) if p[-1] in '12']
            idx = stress[-1] if stress else len(phonemes)-1
            return ''.join(phonemes[idx:])
    orig = w
    norm = orig.translate(str.maketrans("áéíóúü", "aeiouu"))
    vowels = re.findall(r"[aeiou]", norm)
    if not vowels:
        return ''
    return ''.join(vowels[-2:] if len(vowels)>=2 else vowels)


def load_exceptions(path):
    try:
        with open(path, encoding='utf-8') as f:
            return {l.strip().lower() for l in f if l.strip()}
    except Exception as e:
        logger.warning(f"Error leyendo excepciones: {e}")
        return set()


def process_file(path, exceptions, lang):
    base = os.path.splitext(os.path.basename(path))[0]
    parts = base.split(' - ', 1)
    song = parts[0]
    artist = parts[1] if len(parts)==2 else ''
    try:
        text = open(path, encoding='utf-8').read()
    except Exception as e:
        logger.error(f"No se puede leer {path}: {e}")
        return []
    words = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", text)
    records = []
    for w in words:
        lw = w.lower()
        if exceptions and lw in exceptions: continue
        key = get_rhyme_key(lw, lang)
        if key:
            records.append({'song':song,'artist':artist,'rhyme_key':key,'word':lw})
    return records


def compute_stats(df):
    grp = df.groupby('rhyme_key')['word'].count()
    total = len(grp)
    mean = grp.mean() if total else 0
    mx = grp.max() if total else 0
    top = grp.nlargest(10).items()
    return {'total_groups':total,'mean_size':mean,'max_size':mx,'top10':list(top)}


def plot_group_distribution(df):
    grp = df.groupby('rhyme_key')['word'].count()
    fig,ax = plt.subplots()
    ax.hist(grp.values, bins=range(1, grp.max()+2))
    ax.set(xlabel='Tamaño de grupo', ylabel='Número de grupos', title='Distribución de rimas')
    fig.tight_layout()
    return fig


def export_to_excel(df, stats, fig, out):
    writer = pd.ExcelWriter(out, engine='xlsxwriter')
    df.to_excel(writer, 'Data', index=False)
    ws = writer.sheets['Data']
    ws.freeze_panes(1,0)
    for i,col in enumerate(df.columns): ws.set_column(i,i,max(df[col].astype(str).map(len).max(),len(col))+2)
    ss = writer.book.add_worksheet('Stats')
    writer.sheets['Stats']=ss
    r=0
    for k,v in stats.items():
        if k!='top10': ss.write(r,0,k); ss.write(r,1,v); r+=1
    ss.write(r,0,'Top 10')
    for i,(k,v) in enumerate(stats['top10'],start=r+1): ss.write(i,0,k); ss.write(i,1,v)
    img=BytesIO(); fig.savefig(img,format='png'); ss.insert_image(r,3,'',{'image_data':BytesIO(img.getvalue())})
    writer.close()

# --- CLI mode ---
if not USE_STREAMLIT:
    import argparse
    p=argparse.ArgumentParser(description='Analiza rimas múltiples')
    p.add_argument('files',nargs='+',help='TXT con letra song - artist.txt')
    p.add_argument('-e','--exceptions',help='TXT de excepciones')
    p.add_argument('-o','--output_csv',default='all_rimas.csv')
    p.add_argument('-x','--output_excel',nargs='?',const='all_rimas.xlsx')
    p.add_argument('-l','--lang',choices=['es','en'],default='es')
    a=p.parse_args()
    exc=load_exceptions(a.exceptions) if a.exceptions else set()
    recs=[]
    for f in a.files: recs+=process_file(f,exc,a.lang)
    df=pd.DataFrame(recs)
    df.to_csv(a.output_csv,index=False,encoding='utf-8-sig'); logger.info(f'CSV {a.output_csv}')
    stats=compute_stats(df); fig=plot_group_distribution(df)
    if a.output_excel: export_to_excel(df,stats,fig,a.output_excel); logger.info(f'Excel {a.output_excel}')
# --- Streamlit mode ---
else:
    st.title('Análisis de rimas múltiples')
    uploaded=st.file_uploader('Sube letras (.txt)',accept_multiple_files=True)
    exc_path=st.sidebar.file_uploader('Excepciones (.txt)')
    lang=st.sidebar.selectbox('Idioma',['es','en'])
    if uploaded:
        exc=set()
        if exc_path: exc={l.strip().lower() for l in exc_path.getvalue().decode('utf-8').splitlines() if l.strip()}
        recs=[]
        for u in uploaded:
            tmp=u.name; open(tmp,'wb').write(u.read())
            recs+=process_file(tmp,exc,lang)
        df=pd.DataFrame(recs)
        if not df.empty:
            st.dataframe(df)
            stats=compute_stats(df); st.json(stats)
            fig=plot_group_distribution(df); st.pyplot(fig)
            buf=BytesIO(); df.to_csv(buf,index=False,encoding='utf-8-sig'); st.download_button('CSV',buf.getvalue(), 'all_rimas.csv')
            eb=BytesIO(); export_to_excel(df,stats,fig,eb); st.download_button('Excel',eb.getvalue(),'all_rimas.xlsx')
