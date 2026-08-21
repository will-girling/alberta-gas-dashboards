from __future__ import annotations

from pathlib import Path
import html
import math
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path('/Users/willgirling/Desktop/NGTL Project')
FLOW_FILE = PROJECT_ROOT / 'processed' / 'ngtl_daily_flows.csv'
OPS_FILE = PROJECT_ROOT / 'processed' / 'ngtl_operational_metrics.csv'

st.set_page_config(page_title='NGTL System Monitor', page_icon='◼', layout='wide', initial_sidebar_state='collapsed')

st.markdown('''
<style>
:root{--panel:rgba(22,28,38,.96);--border:rgba(255,255,255,.11);--text:#f3f5f7;--muted:#9aa4b2;--positive:#66d19e;--negative:#ff8b8b;--neutral:#d7dde5}
.block-container{max-width:1600px;padding-top:1.25rem;padding-bottom:2.5rem}
.dashboard-title{font-size:2rem;font-weight:750;margin-bottom:.15rem}.dashboard-subtitle{color:var(--muted);font-size:.95rem;margin-bottom:1.1rem}
.status-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:.35rem 0 1rem}.status-card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:.85rem 1rem;min-height:84px}.status-label{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.06em}.status-value{color:var(--text);font-size:1.35rem;font-weight:720;margin-top:.15rem}.status-detail{color:var(--muted);font-size:.78rem;margin-top:.15rem}
.map-shell{position:relative;height:690px;min-width:760px;overflow:hidden;border-radius:16px;background:radial-gradient(circle at 46% 42%,rgba(70,85,105,.13),transparent 38%),linear-gradient(180deg,rgba(20,26,36,.98),rgba(15,20,29,.98));border:1px solid var(--border)}
.alberta-shape{position:absolute;left:25%;top:7%;width:51%;height:84%;background:rgba(96,111,132,.10);border:2px solid rgba(170,184,204,.24);clip-path:polygon(18% 0%,77% 1%,83% 18%,84% 33%,91% 47%,89% 69%,95% 86%,83% 99%,22% 98%,17% 84%,13% 67%,8% 52%,10% 34%,13% 17%)}
.province-label{position:absolute;left:46%;top:47%;transform:translate(-50%,-50%);color:rgba(230,235,242,.11);font-size:3.3rem;font-weight:800;letter-spacing:.16em;writing-mode:vertical-rl}
.flow-card{position:absolute;width:172px;min-height:110px;background:rgba(27,34,45,.96);border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:.72rem .8rem;box-shadow:0 10px 24px rgba(0,0,0,.22);z-index:4}.flow-card.core{width:195px;background:rgba(34,42,55,.98)}
.flow-title{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.055em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.flow-value{color:var(--text);font-size:1.43rem;font-weight:760;margin:.13rem 0}.flow-change{font-size:.78rem;font-weight:600}.flow-sub{color:var(--muted);font-size:.72rem;line-height:1.25;margin-top:.22rem}.positive{color:var(--positive)}.negative{color:var(--negative)}.neutral{color:var(--neutral)}
.west-line,.east-line{position:absolute;height:1px;background:rgba(190,202,218,.20);z-index:2;transform-origin:left center}
.summary-panel{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:.8rem .9rem 1rem .9rem;min-height:690px}.summary-heading{color:var(--text);font-size:1rem;font-weight:700;margin:.15rem 0 .7rem 0}.summary-note{color:var(--muted);font-size:.75rem;margin-bottom:.75rem}
div[data-testid='stDataFrame']{border:1px solid rgba(255,255,255,.08);border-radius:10px;overflow:hidden}
@media(max-width:1100px){.status-row{grid-template-columns:repeat(2,minmax(0,1fr))}.map-shell{min-width:720px}}
</style>
''', unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def load_data():
    if not FLOW_FILE.exists():
        raise FileNotFoundError(f'Flow file not found: {FLOW_FILE}')
    flows = pd.read_csv(FLOW_FILE)
    flows['GasDay'] = pd.to_datetime(flows['GasDay'], errors='coerce')
    for col in ['ProratedMMcfd','ExtrapolatedMMcfd','NextDayNominatedMMcfd']:
        if col in flows.columns:
            flows[col] = pd.to_numeric(flows[col], errors='coerce')
    if OPS_FILE.exists():
        ops = pd.read_csv(OPS_FILE)
        ops['GasDay'] = pd.to_datetime(ops['GasDay'], errors='coerce')
        if 'NumericValue' in ops.columns:
            ops['NumericValue'] = pd.to_numeric(ops['NumericValue'], errors='coerce')
    else:
        ops = pd.DataFrame(columns=['GasDay','Metric','NumericValue','TextValue','SourceFile'])
    return flows.dropna(subset=['GasDay']).sort_values(['GasDay','Item']), ops.dropna(subset=['GasDay']).sort_values(['GasDay','Metric'])

def norm(x):
    return re.sub(r'\s+',' ',re.sub(r'[^A-Z0-9]+',' ',str(x).upper().replace('&','AND'))).strip()

def find_name(df, column, candidates):
    if df.empty or column not in df.columns:
        return None
    mapping = {norm(v): v for v in df[column].dropna().astype(str).unique()}
    for c in candidates:
        if norm(c) in mapping:
            return mapping[norm(c)]
    for c in candidates:
        ct = set(norm(c).split())
        for k,v in mapping.items():
            if ct and ct.issubset(set(k.split())):
                return v
    return None

def series_from(df, name, value_col, label_col):
    if not name:
        return pd.Series(dtype='float64')
    x = df.loc[df[label_col] == name, ['GasDay', value_col]].drop_duplicates('GasDay', keep='last')
    return x.set_index('GasDay')[value_col].sort_index()

def value_at(s, d):
    if s.empty or d not in s.index: return math.nan
    v=s.loc[d]
    return v.iloc[-1] if isinstance(v,pd.Series) else v

def prev_value(s,d):
    x=s.loc[s.index<d]
    return x.iloc[-1] if not x.empty else math.nan

def snap(s,d):
    cur=value_at(s,d); prev=prev_value(s,d); a14=s.loc[:d].tail(14).mean() if not s.empty else math.nan; a30=s.loc[:d].tail(30).mean() if not s.empty else math.nan
    return {'current':cur,'previous':prev,'change':cur-prev if pd.notna(cur) and pd.notna(prev) else math.nan,'avg14':a14,'avg30':a30,'vs14':cur-a14 if pd.notna(cur) and pd.notna(a14) else math.nan,'vs30':cur-a30 if pd.notna(cur) and pd.notna(a30) else math.nan}

def fmt(v,signed=False):
    if v is None or pd.isna(v): return '—'
    return f'{v/1000:+.2f}' if signed else f'{v/1000:.2f}'

def cls(v):
    if pd.isna(v) or abs(v)<5: return 'neutral'
    return 'positive' if v>0 else 'negative'

def card(title,s,n,left,top,core=False,note='Positive = into NGTL; negative = out of NGTL'):
    ch='No prior value' if pd.isna(s['change']) else f"{fmt(s['change'],True)} Bcf/d vs prior day"
    return f"""<div class='flow-card {'core' if core else ''}' style='left:{left};top:{top};'><div class='flow-title'>{html.escape(title)}</div><div class='flow-value'>{fmt(s['current'])} Bcf/d</div><div class='flow-change {cls(s['change'])}'>{ch}</div><div class='flow-sub'>Nom: {fmt(n)} Bcf/d<br>14d: {fmt(s['avg14'])} · 30d: {fmt(s['avg30'])}<br>{html.escape(note)}</div></div>"""

def status(label,value,detail):
    return f"<div class='status-card'><div class='status-label'>{html.escape(label)}</div><div class='status-value'>{html.escape(value)}</div><div class='status-detail'>{html.escape(detail)}</div></div>"

try:
    flows,ops=load_data()
except Exception as e:
    st.error(str(e)); st.stop()

days=sorted(flows['GasDay'].dt.normalize().dropna().unique())
selected=pd.Timestamp(st.select_slider('Gas Day', options=days, value=days[-1], format_func=lambda x: pd.Timestamp(x).strftime('%b %d, %Y')))

st.markdown("<div class='dashboard-title'>NGTL System Monitor</div>",unsafe_allow_html=True)
st.markdown("<div class='dashboard-subtitle'>Daily system balance, border flows, storage and linepack context</div>",unsafe_allow_html=True)

items={
'Empress':['EMPRESS BORDER'],'McNeill':['MCNEILL BORDER'],'Alberta–BC':['ALBERTA-B.C. BDR','ALBERTA BC BORDER'],'Gordondale':['GORDONDALE BORDER'],'Groundbirch East':['GROUNDBIRCH EAST'],'Willow Valley':['WILLOW VALLEY INTERCONNECT'],'Intraprovincial':['INTRAPROVINCIAL'],'Net Storage':['TOTAL NET STORAGE'],'Total Deliveries':['TOTAL NGTL DELIVERIES'],'Total Receipts':['TOTAL NGTL RECEIPTS']}
ops_names={'Field Receipts':['NGTL FIELD RECEIPTS','FIELD RECEIPTS'],'Linepack':['END OF DAY LINEPACK'],'Linepack Target':['LINEPACK TARGET']}
resolved={k:find_name(flows,'Item',v) for k,v in items.items()}; resolved_ops={k:find_name(ops,'Metric',v) for k,v in ops_names.items()}
series={k:series_from(flows,v,'ExtrapolatedMMcfd','Item') for k,v in resolved.items()}; opseries={k:series_from(ops,v,'NumericValue','Metric') for k,v in resolved_ops.items()}
snaps={k:snap(v,selected) for k,v in series.items()}; opsnaps={k:snap(v,selected) for k,v in opseries.items()}
selrows=flows.loc[flows['GasDay'].dt.normalize()==selected]
nom={}
for k,v in resolved.items():
    x=selrows.loc[selrows['Item']==v,'NextDayNominatedMMcfd'] if v else pd.Series(dtype='float64')
    nom[k]=x.iloc[-1] if not x.empty else math.nan

field=opsnaps.get('Field Receipts',snap(pd.Series(dtype='float64'),selected)); lp=opsnaps.get('Linepack',snap(pd.Series(dtype='float64'),selected)); lpt=opsnaps.get('Linepack Target',snap(pd.Series(dtype='float64'),selected))
lpgap=lp['current']-lpt['current'] if pd.notna(lp['current']) and pd.notna(lpt['current']) else math.nan
parts=[]
if pd.notna(snaps['Total Deliveries']['vs14']): parts.append(snaps['Total Deliveries']['vs14'])
if pd.notna(snaps['Net Storage']['vs14']): parts.append(-snaps['Net Storage']['vs14'])
if pd.notna(lpgap): parts.append(-lpgap)
raw=sum(parts) if parts else math.nan
condition='Insufficient data' if pd.isna(raw) else ('Tighter than recent' if raw>250 else ('Looser than recent' if raw<-250 else 'Near recent balance'))

st.markdown("<div class='status-row'>"+status('Selected gas day',selected.strftime('%b %d, %Y'),f"Latest available: {pd.Timestamp(days[-1]).strftime('%b %d, %Y')}")+status('System condition',condition,'Directional indicator from deliveries, storage and linepack')+status('Field receipts',f"{fmt(field['current'])} Bcf/d",f"14-day average: {fmt(field['avg14'])} Bcf/d")+status('Linepack vs target',f"{fmt(lpgap,True)} Bcf",f"Linepack: {fmt(lp['current'])} · Target: {fmt(lpt['current'])}")+"</div>",unsafe_allow_html=True)

left,right=st.columns([2.35,1.05],gap='large')
with left:
    map_html=f"""<div class='map-shell'><div class='alberta-shape'></div><div class='province-label'>ALBERTA</div>
    {card('Gordondale',snaps['Gordondale'],nom['Gordondale'],'2.5%','10%')}
    {card('Alberta–BC',snaps['Alberta–BC'],nom['Alberta–BC'],'2.5%','31%')}
    {card('Groundbirch East',snaps['Groundbirch East'],nom['Groundbirch East'],'2.5%','52%')}
    {card('Willow Valley',snaps['Willow Valley'],nom['Willow Valley'],'2.5%','73%')}
    {card('Field Receipts',field,math.nan,'37%','13%',True,'Operational metric')}
    {card('Intraprovincial',snaps['Intraprovincial'],nom['Intraprovincial'],'38%','36%',True)}
    {card('Total Deliveries',snaps['Total Deliveries'],nom['Total Deliveries'],'38%','59%',True)}
    {card('Net Storage',snaps['Net Storage'],nom['Net Storage'],'38%','79%',True,'Sign follows source report')}
    {card('Empress',snaps['Empress'],nom['Empress'],'76.5%','27%')}
    {card('McNeill',snaps['McNeill'],nom['McNeill'],'76.5%','54%')}
    <div class='west-line' style='left:20%;top:17%;width:17%;transform:rotate(8deg)'></div><div class='west-line' style='left:20%;top:38%;width:18%;transform:rotate(3deg)'></div><div class='west-line' style='left:20%;top:59%;width:18%;transform:rotate(-4deg)'></div><div class='west-line' style='left:20%;top:80%;width:18%;transform:rotate(-8deg)'></div><div class='east-line' style='left:63%;top:41%;width:14%;transform:rotate(-9deg)'></div><div class='east-line' style='left:63%;top:64%;width:14%;transform:rotate(7deg)'></div></div>"""
    st.markdown(map_html,unsafe_allow_html=True)
with right:
    st.markdown("<div class='summary-panel'><div class='summary-heading'>Current vs recent balance</div><div class='summary-note'>Values are extrapolated flows in Bcf/d. Differences are current minus average.</div>",unsafe_allow_html=True)
    order=['Field Receipts','Intraprovincial','Total Deliveries','Net Storage','Empress','McNeill','Alberta–BC','Gordondale','Groundbirch East','Willow Valley']
    rows=[]
    for label in order:
        s=field if label=='Field Receipts' else snaps[label]
        rows.append({'Metric':label,'Current':None if pd.isna(s['current']) else round(s['current']/1000,2),'14d avg':None if pd.isna(s['avg14']) else round(s['avg14']/1000,2),'30d avg':None if pd.isna(s['avg30']) else round(s['avg30']/1000,2),'vs 14d':None if pd.isna(s['vs14']) else round(s['vs14']/1000,2),'vs 30d':None if pd.isna(s['vs30']) else round(s['vs30']/1000,2)})
    sdf=pd.DataFrame(rows).set_index('Metric')
    st.dataframe(sdf.style.format({'Current':'{:.2f}','14d avg':'{:.2f}','30d avg':'{:.2f}','vs 14d':'{:+.2f}','vs 30d':'{:+.2f}'},na_rep='—'),use_container_width=True,height=520)
    st.caption('Negative border values generally indicate gas leaving NGTL. Storage sign treatment is retained from the source report.')
    st.markdown('</div>',unsafe_allow_html=True)

st.markdown('### Historical context')
options=['Field Receipts','Intraprovincial','Total Deliveries','Net Storage','Empress','McNeill','Alberta–BC','Gordondale','Groundbirch East','Willow Valley']
metric=st.selectbox('Metric',options,index=2,label_visibility='collapsed')
cs=opseries['Field Receipts'] if metric=='Field Receipts' else series[metric]
cd=cs.loc[:selected].tail(120).dropna()
fig=go.Figure()
fig.add_trace(go.Scatter(x=cd.index,y=cd.values/1000,mode='lines',name=metric,hovertemplate='%{x|%b %d, %Y}<br>%{y:.2f} Bcf/d<extra></extra>'))
fig.add_trace(go.Scatter(x=cd.index,y=cd.rolling(14,min_periods=3).mean()/1000,mode='lines',name='14-day average'))
fig.add_trace(go.Scatter(x=cd.index,y=cd.rolling(30,min_periods=5).mean()/1000,mode='lines',name='30-day average'))
fig.add_vline(x=selected,line_dash='dot')
fig.update_layout(height=390,margin=dict(l=20,r=20,t=20,b=20),xaxis_title=None,yaxis_title='Bcf/d',legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='left',x=0),hovermode='x unified')
st.plotly_chart(fig,use_container_width=True)

with st.expander('Resolved source labels'):
    diag=pd.DataFrame([{'Dashboard label':k,'Resolved source item':v} for k,v in {**resolved,**resolved_ops}.items()])
    st.dataframe(diag,use_container_width=True,hide_index=True)
