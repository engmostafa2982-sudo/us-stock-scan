"""
30-Point Full-Spectrum Scoring Engine (v3) — faithful implementation of the
anthropic-skills:30-point-scoring rubric for batch market-wide scanning.

Implements all 31 indicators across 7 categories plus adjustment Rules 2-19:
v2: MCT (R13), CQ (R5v2), MHM (R6v2), Distribution gate (R9), Penalty cap (R12)
v3 NEW: Exhaustion Detection (R14), Volume Acceleration (R15),
        Days-Since-Breakout Decay (R16), Close Position Signal (R17),
        Momentum Direction Modifier (R18), Coiled Spring Bonus (R19)

Proxied/defaulted (documented): Put/Call -> neutral 2; Sector/breadth -> RS vs SPY;
Catalyst CQ -> CQ-C; order book (D3), seasonals (D5), institutional (MCT5),
catalyst (MCT4) -> off. These are unbatchable across 3,700 names.
"""
import os, json, math, time, csv
import numpy as np
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(__file__)
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

def load_key():
    # 1. Environment variable (GitHub Actions / cloud)
    key = os.environ.get("EODHD_API_KEY", "")
    if key:
        return key
    # 2. Local .env file (laptop)
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("EODHD_API_KEY"):
                    return line.strip().split("=", 1)[1]
    raise RuntimeError("EODHD_API_KEY not found in env or .env file")
KEY = load_key()

# ------------------------------------------------------------------ data fetch
def fetch_eod(code, frm="2025-03-01"):
    sym = code if "." in code else code + ".US"   # screener codes are bare
    cf = os.path.join(CACHE, sym.replace("/", "_") + ".json")
    if os.path.exists(cf):
        try:
            with open(cf) as f:
                return pd.DataFrame(json.load(f))
        except Exception:
            pass
    url = f"https://eodhd.com/api/eod/{sym}"
    for attempt in range(3):
        try:
            r = requests.get(url, params={"api_token": KEY, "fmt": "json",
                                          "period": "d", "from": frm}, timeout=30)
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, list) or len(data) < 30:
                return None
            with open(cf, "w") as f:
                json.dump(data, f)
            return pd.DataFrame(data)
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2 ** attempt)
    return None

# ------------------------------------------------------------------ indicator math
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100/(1+rs)).fillna(50)

def macd(s):
    line = ema(s,12) - ema(s,26)
    sig = ema(line,9)
    return line, sig, line-sig

def true_range(df):
    h,l,c = df.high, df.low, df.close
    pc = c.shift()
    return pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)

def atr(df,n=14): return true_range(df).ewm(alpha=1/n,adjust=False).mean()

def adx(df,n=14):
    h,l = df.high, df.low
    up = h.diff(); dn = -l.diff()
    plus = np.where((up>dn)&(up>0), up, 0.0)
    minus = np.where((dn>up)&(dn>0), dn, 0.0)
    tr = true_range(df)
    atrn = tr.ewm(alpha=1/n,adjust=False).mean().replace(0,np.nan)
    pdi = 100*pd.Series(plus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/atrn
    mdi = 100*pd.Series(minus,index=df.index).ewm(alpha=1/n,adjust=False).mean()/atrn
    dx = 100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean().fillna(0), pdi.fillna(0), mdi.fillna(0)

def stoch(df,n=14,d=3):
    ll = df.low.rolling(n).min(); hh = df.high.rolling(n).max()
    k = 100*(df.close-ll)/(hh-ll).replace(0,np.nan)
    return k.fillna(50), k.rolling(d).mean().fillna(50)

def cci(df,n=20):
    tp = (df.high+df.low+df.close)/3
    ma = tp.rolling(n).mean()
    md = (tp-ma).abs().rolling(n).mean()
    return ((tp-ma)/(0.015*md.replace(0,np.nan))).fillna(0)

def williams_r(df,n=14):
    hh=df.high.rolling(n).max(); ll=df.low.rolling(n).min()
    return (-100*(hh-df.close)/(hh-ll).replace(0,np.nan)).fillna(-50)

def roc(s,n=12): return (s/s.shift(n)-1).fillna(0)*100

def mfi(df,n=14):
    tp=(df.high+df.low+df.close)/3; rmf=tp*df.volume
    pos=rmf.where(tp>tp.shift(),0.0).rolling(n).sum()
    neg=rmf.where(tp<tp.shift(),0.0).rolling(n).sum().replace(0,np.nan)
    return (100-100/(1+pos/neg)).fillna(50)

def tsi(s,r=25,sm=13):
    m=s.diff()
    ds=ema(ema(m,r),sm); da=ema(ema(m.abs(),r),sm).replace(0,np.nan)
    t=100*ds/da
    return t.fillna(0), ema(t.fillna(0),7)

def bollinger(s,n=20,k=2):
    m=sma(s,n); sd=s.rolling(n).std()
    return m+k*sd, m, m-k*sd, sd

def obv(df):
    sign=np.sign(df.close.diff()).fillna(0)
    return (sign*df.volume).cumsum()

def ad_line(df):
    rng=(df.high-df.low).replace(0,np.nan)
    mfm=((df.close-df.low)-(df.high-df.close))/rng
    return (mfm.fillna(0)*df.volume).cumsum()

def cmf(df,n=20):
    rng=(df.high-df.low).replace(0,np.nan)
    mfv=(((df.close-df.low)-(df.high-df.close))/rng).fillna(0)*df.volume
    return (mfv.rolling(n).sum()/df.volume.rolling(n).sum().replace(0,np.nan)).fillna(0)

def psar(df,af0=0.02,afmax=0.2):
    h=df.high.values; l=df.low.values; n=len(df)
    ps=np.zeros(n); bull=True; af=af0; ep=l[0]; sar=l[0]
    for i in range(1,n):
        sar=sar+af*(ep-sar)
        if bull:
            if l[i]<sar:
                bull=False; sar=ep; ep=l[i]; af=af0
            else:
                if h[i]>ep: ep=h[i]; af=min(af+af0,afmax)
        else:
            if h[i]>sar:
                bull=True; sar=ep; ep=h[i]; af=af0
            else:
                if l[i]<ep: ep=l[i]; af=min(af+af0,afmax)
        ps[i]=sar
    return pd.Series(ps,index=df.index)

def supertrend(df,n=10,mult=3):
    a=atr(df,n); hl2=(df.high+df.low)/2
    up=hl2-mult*a; dn=hl2+mult*a
    st=np.zeros(len(df)); dir_=np.ones(len(df))
    fu=up.values.copy(); fl=dn.values.copy(); c=df.close.values
    for i in range(1,len(df)):
        fu[i]=max(up.values[i],fu[i-1]) if c[i-1]>fu[i-1] else up.values[i]
        fl[i]=min(dn.values[i],fl[i-1]) if c[i-1]<fl[i-1] else dn.values[i]
    for i in range(1,len(df)):
        if c[i]>fl[i-1]: dir_[i]=1
        elif c[i]<fu[i-1]: dir_[i]=-1
        else: dir_[i]=dir_[i-1]
        st[i]=fu[i] if dir_[i]==1 else fl[i]
    return pd.Series(st,index=df.index), pd.Series(dir_,index=df.index)

def ichimoku(df):
    conv=(df.high.rolling(9).max()+df.low.rolling(9).min())/2
    base=(df.high.rolling(26).max()+df.low.rolling(26).min())/2
    spanA=((conv+base)/2).shift(26)
    spanB=((df.high.rolling(52).max()+df.low.rolling(52).min())/2).shift(26)
    return conv,base,spanA,spanB

def slope(s):
    y=s.dropna().values
    if len(y)<3: return 0.0
    x=np.arange(len(y))
    return np.polyfit(x,y,1)[0]

def pct_rank(s, val):
    s=s.dropna()
    if len(s)<5: return 50.0
    return (s<val).mean()*100

# ------------------------------------------------------------------ v3 new rules (R14–R19)
def compute_exhaustion(df):
    """Rule 14 — Exhaustion Detection Penalty (v3). Returns (penalty, signal_count)."""
    c=df.close; v=df.volume; n=len(df)
    if n<22: return 0, 0
    rv=rsi(c); last=-1; px=c.iloc[last]

    # EX1: RSI was >70 within last 3 sessions AND is now falling
    ex1=0
    if len(rv)>=4:
        rsi_now=rv.iloc[last]
        rsi_prev3=rv.iloc[-4:-1]
        if rsi_prev3.max()>70 and rsi_now<rv.iloc[-2]:
            ex1=-3

    # EX2: Price >2σ above 20-day MA
    ex2=0
    ma20=c.rolling(20).mean().iloc[last]
    std20=c.rolling(20).std().iloc[last]
    if std20>0 and (px-ma20)>2*std20:
        ex2=-3

    # EX3: Volume >1.5× 20-day avg for 3+ consecutive sessions
    ex3=0
    avgv20=v.rolling(20).mean()
    consec=sum(1 for i in range(-3,0) if avgv20.iloc[i]>0 and v.iloc[i]>1.5*avgv20.iloc[i])
    if consec>=3: ex3=-3

    # EX4: Closed in bottom 30% of range after opening in top 50% (intraday reversal)
    ex4=0
    h_=df.high.iloc[last]; l_=df.low.iloc[last]
    o_=df.open.iloc[last]; c_=c.iloc[last]
    rng_=(h_-l_) or 1e-9
    if (c_-l_)/rng_<=0.30 and (o_-l_)/rng_>=0.50:
        ex4=-4

    # EX5: MACD histogram shrinking 2+ consecutive bars while price rising
    ex5=0
    _,_,mhist=macd(c)
    if len(mhist)>=4:
        hv=mhist.iloc[-4:].values
        if hv[-1]<hv[-2]<hv[-3] and c.iloc[-1]>c.iloc[-2]:
            ex5=-3

    total=ex1+ex2+ex3+ex4+ex5
    count=sum(1 for x in [ex1,ex2,ex3,ex4,ex5] if x<0)
    return total, count


def compute_volume_acceleration(df):
    """Rule 15 — Volume Acceleration Bonus/Penalty (v3, exempt from R12 cap)."""
    c=df.close; v=df.volume; n=len(df)
    if n<21: return 0
    avgv=v.rolling(20).mean().iloc[-1]
    if avgv<=0: return 0
    var=v.iloc[-1]/avgv
    green=c.iloc[-1]>df.open.iloc[-1]

    # Volume compression → acceleration (pre-breakout coiling detection)
    if n>=7:
        if all(v.iloc[i]>=v.iloc[i+1] for i in range(-7,-1)) and var>=1.5 and green:
            return 3  # "coiling spring releasing"

    if var>=4.0 and green:     return 5
    elif var>=2.5 and green:   return 3
    elif var>=1.5 and green:   return 1
    elif var<1.0 and green:    return -2
    elif var>=2.5 and not green: return -4
    return 0


def compute_breakout_decay(df):
    """Rule 16 — Days-Since-Breakout Decay multiplier for Category 6 Pattern (v3)."""
    c=df.close; n=len(df)
    if n<26: return 1.0
    decay={0:1.00, 1:0.90, 2:0.80, 3:0.70, 4:0.55}
    for days_since in range(0,6):
        k=n-1-days_since  # absolute index of candidate breakout candle
        if k<22: break
        prior_high=c.iloc[k-21:k-1].max()
        if c.iloc[k]>prior_high and c.iloc[k-1]<=prior_high:
            return decay.get(days_since, 0.40)
    return 1.0  # No recent breakout — no decay


def compute_close_position(df):
    """Rule 17 — Intraday Close Position Signal (v3). Returns penalty (negative) or bonus."""
    n=len(df)
    if n<10: return 0
    h_=df.high.iloc[-1]; l_=df.low.iloc[-1]
    o_=df.open.iloc[-1]; c_=df.close.iloc[-1]
    v=df.volume
    rng_=(h_-l_) or 1e-9
    cp=(c_-l_)/rng_*100  # 0-100
    avgv=v.rolling(20).mean().iloc[-1] if n>=20 else v.mean()
    vol_up=v.iloc[-1]>v.iloc[-2] if n>=2 else False
    vol_spike=avgv>0 and v.iloc[-1]>2*avgv
    at_high=c_>=df.high.iloc[-6:-1].max()*0.97 if n>=6 else False
    op_pos=(o_-l_)/rng_
    was_at_highs=op_pos>=0.70
    up_days=sum(1 for i in range(-5,-1) if df.close.iloc[i]>df.close.iloc[i-1]) if n>=6 else 0

    if cp<=5 and up_days>=3:      return -5  # failed continuation after run
    if cp<=20 and was_at_highs:   return -4  # intraday reversal / distribution
    if cp<=20 and not at_high and vol_spike: return 2  # capitulation at lows
    if cp>=80 and at_high:
        return 2 if vol_up else -3   # strong close vs exhaustion close
    return 0


def compute_momentum_direction(df):
    """Rule 18 — Momentum Direction Modifier (v3). Returns adjustment (±5 max)."""
    c=df.close; n=len(df)
    if n<20: return 0
    rv=rsi(c)
    if len(rv)<5: return 0
    rsi_now=rv.iloc[-1]; rsi_3ago=rv.iloc[-4]
    rsi_rising=rsi_now>rsi_3ago
    mod=0

    # RSI direction modifier
    if rsi_rising:
        if 40<=rsi_now<=60:   mod+=2
        elif 60<rsi_now<=70:  mod+=1
    else:
        if 60<=rsi_now<=70:   mod-=2
        elif rsi_now>70:      mod-=3

    # Stochastic modifier
    k_,d_=stoch(df)
    if len(k_)>=5 and len(d_)>=1:
        kn=k_.iloc[-1]; k3=k_.iloc[-4]; dn=d_.iloc[-1]
        if kn<k3 and kn>80 and dn>80: mod-=2  # bearish cross from overbought
        elif kn>k3 and kn<30 and kn>dn: mod+=2  # bullish cross from oversold

    return max(-5, min(5, mod))


def compute_coiled_spring(df):
    """Rule 19 — Coiled Spring Bonus (v3, exempt from cap, mutex with R14)."""
    c=df.close; v=df.volume; n=len(df)
    if n<55: return 0
    px=c.iloc[-1]

    # CS1: BB Width at/near 20-day minimum (bands narrowing)
    _,_,_,bbsd=bollinger(c,20,2)
    bbm_=sma(c,20)
    bb_w=(4*bbsd/bbm_.replace(0,np.nan)).fillna(0)
    cs1=bool(bb_w.iloc[-1]<=bb_w.iloc[-20:].min()*1.15)

    # CS2: Volume declining for 3+ sessions (participation drying up)
    cs2=n>=5 and all(v.iloc[i]>=v.iloc[i+1] for i in range(-5,-1))

    # CS3: Price above SMA 50 AND EMA 21 (healthy trend, just resting)
    s50=sma(c,50).iloc[-1]; e21=ema(c,21).iloc[-1]
    cs3=bool(px>s50 and px>e21)

    # CS4: RSI in neutral zone 40-55 (not weak, not overbought)
    rv=rsi(c)
    cs4=bool(40<=rv.iloc[-1]<=55)

    # CS5: Price near key support (within 5% of SMA 50 or near 20-day low)
    look=df.iloc[-20:] if n>=20 else df
    near_sma50=abs(px-s50)/(s50 or 1)<0.05
    near_low=px<=look.low.min()*1.08
    cs5=bool(near_sma50 or near_low)

    count=sum([cs1,cs2,cs3,cs4,cs5])
    if count>=5: return 8
    elif count>=4: return 5
    elif count>=3: return 3
    return 0


# ------------------------------------------------------------------ category scoring
def score_categories(df, spy_ret20=None):
    """Returns (cat_scores dict, detail dict of useful raw values)."""
    c=df.close; v=df.volume
    n=len(df)
    last=-1
    px=c.iloc[last]
    s50=sma(c,50); s200=sma(c,200)
    e9=ema(c,9); e21=ema(c,21); e20=ema(c,20)
    ml,msig,mh=macd(c)
    adxv,pdi,mdi=adx(df)
    sar=psar(df)
    conv,base,spanA,spanB=ichimoku(df)
    st,stdir=supertrend(df)
    r=rsi(c); k,dd=stoch(df); cc=cci(df); wr=williams_r(df)
    rc=roc(c); mf=mfi(df); ts,tsig=tsi(c)
    bbu,bbm,bbl,bbsd=bollinger(c); a=atr(df)
    kcm=ema(c,20); kca=atr(df,20); kcu=kcm+2*kca; kcl=kcm-2*kca
    don_u=df.high.rolling(20).max(); don_l=df.low.rolling(20).min()
    ob=obv(df); ad=ad_line(df); cf=cmf(df)
    det={}

    # ---- TREND (21)
    t=0
    above50=px>s50.iloc[last] if not math.isnan(s50.iloc[last]) else px>c.mean()
    above200=px>s200.iloc[last] if not math.isnan(s200.iloc[last]) else above50
    gc = (s50.iloc[last]>s200.iloc[last]) if not math.isnan(s200.iloc[last]) else above50
    if above50 and above200: t1=4 if gc else 2
    elif above50 or above200: t1=2
    else: t1=0
    # EMA9/21
    cross_age=99
    cu=(e9>e21)
    for i in range(1,min(8,n)):
        if cu.iloc[-i] and not cu.iloc[-i-1]: cross_age=i; break
    if e9.iloc[last]>e21.iloc[last]:
        t2=3 if (px>e9.iloc[last] and cross_age<=5) else (2 if px>e21.iloc[last] else 1)
    else:
        gap=(e21.iloc[last]-e9.iloc[last])/px
        t2=1 if gap<0.01 else 0
    # MACD
    if ml.iloc[last]>msig.iloc[last]:
        t3=3 if (ml.iloc[last]>ml.iloc[-2] and msig.iloc[last]>msig.iloc[-2]) else 2
    else:
        t3=1 if mh.iloc[last]>mh.iloc[-2] else 0
    # ADX
    if pdi.iloc[last]>mdi.iloc[last]:
        t4=3 if adxv.iloc[last]>25 else (2 if adxv.iloc[last]>=20 else 1)
    else: t4=0
    # PSAR
    if sar.iloc[last]<px:
        flip=any(sar.iloc[-i]<df.close.iloc[-i] and sar.iloc[-i-1]>df.close.iloc[-i-1] for i in range(1,min(6,n)))
        t5=3 if flip else 2
    else: t5=0
    # Ichimoku
    ct=max(spanA.iloc[last],spanB.iloc[last]); cb=min(spanA.iloc[last],spanB.iloc[last])
    if not math.isnan(ct):
        if px>ct:
            chikou_ok = px>c.iloc[-27] if n>27 else True
            t6=3 if (conv.iloc[last]>base.iloc[last] and chikou_ok) else 2
        elif px<cb: t6=0
        else: t6=1
    else: t6=1
    # SuperTrend
    if st.iloc[last]<px:
        flip=any(stdir.iloc[-i]==1 and stdir.iloc[-i-1]==-1 for i in range(1,min(6,n)))
        t7=2 if flip else 1
    else: t7=0
    trend=t1+t2+t3+t4+t5+t6+t7

    # ---- MOMENTUM (18)
    rv=r.iloc[last]; rising=r.iloc[last]>r.iloc[-2]
    if 50<=rv<=65 and rising: m8=3
    elif (40<=rv<50 and rising) or (65<rv<=70): m8=2
    elif 40<=rv<=72: m8=1
    else: m8=0
    det['rsi']=rv
    if k.iloc[last]>dd.iloc[last]:
        if k.iloc[last]>80: m9=1
        elif k.iloc[last]<35: m9=3
        else: m9=2
    else: m9=0
    ccv=cc.iloc[last]; ccr=cc.iloc[last]>cc.iloc[-2]
    if ccr and ccv>-100: m10=2
    elif -100<ccv<=0: m10=1
    else: m10=0
    wv=wr.iloc[last]; wrr=wr.iloc[last]>wr.iloc[-2]
    if wv>-20: m11=0
    elif wv<-50 and wrr: m11=2
    else: m11=1
    if rc.iloc[last]>0 and rc.iloc[last]>rc.iloc[-2]: m12=2
    elif rc.iloc[last]>-2 and rc.iloc[last]>rc.iloc[-2]: m12=1
    else: m12=0
    mfv=mf.iloc[last]; mfr=mf.iloc[last]>mf.iloc[-2]
    if 40<=mfv<=70 and mfr: m13=3
    elif 20<=mfv<40 and mfr: m13=2
    elif 20<=mfv<=80: m13=1
    else: m13=0
    if ts.iloc[last]>tsig.iloc[last]:
        m14=3 if ts.iloc[last]>ts.iloc[-2] else 2
    else: m14=1 if ts.iloc[last]>ts.iloc[-2] else 0
    momentum=m8+m9+m10+m11+m12+m13+m14

    # ---- VOLATILITY (14)
    width=((bbu-bbl)/bbm.replace(0,np.nan))
    wpr=pct_rank(width.iloc[-126:], width.iloc[last])
    if wpr<=10: v15=4
    elif wpr<=30: v15=2
    elif width.iloc[last]<width.iloc[-2]: v15=1
    else: v15=0
    atrp=pct_rank((a/c).iloc[-126:], (a.iloc[last]/px))
    if atrp<=25: v16=3
    elif atrp<=60: v16=2
    elif atrp<=85: v16=1
    else: v16=0
    squeeze_on = bbl.iloc[last]>kcl.iloc[last] and bbu.iloc[last]<kcu.iloc[last]
    if px>kcu.iloc[last] and any((bbl.iloc[-i]>kcl.iloc[-i] and bbu.iloc[-i]<kcu.iloc[-i]) for i in range(1,min(8,n))):
        v17=3
    elif px>kcm.iloc[last] and px>(kcm.iloc[last]+0.6*(kcu.iloc[last]-kcm.iloc[last])): v17=2
    elif px>kcm.iloc[last]: v17=1
    else: v17=0
    if px>=don_u.iloc[-2]*0.999: v18=2
    elif px>=don_l.iloc[last]+0.8*(don_u.iloc[last]-don_l.iloc[last]): v18=1
    else: v18=0
    sdp=pct_rank(bbsd.iloc[-126:], bbsd.iloc[last])
    if sdp<=25 and bbsd.iloc[last]>bbsd.iloc[-2]: v19=2
    elif sdp<=35: v19=1
    else: v19=0
    volat=v15+v16+v17+v18+v19

    # ---- VOLUME (18)
    obs=slope(ob.iloc[-20:]); prs=slope(c.iloc[-20:])
    if obs>0 and prs>0: u20=4
    elif obs>0: u20=3
    elif abs(obs)<1e-9: u20=2
    else: u20=0
    tp=(df.high+df.low+df.close)/3
    vwap=(tp*v).rolling(20).sum()/v.rolling(20).sum().replace(0,np.nan)
    if px>vwap.iloc[last]*1.01: u21=2
    elif px>vwap.iloc[last]*0.99: u21=1
    else: u21=0
    ads=slope(ad.iloc[-20:])
    u22=3 if ads>0 else (1 if abs(ads)<1e-9 else 0)
    if ads>0 and ad.iloc[-20:].std()>0: u22=3 if ads>0 else u22
    cfv=cf.iloc[last]
    if cfv>0.05 and cf.iloc[last]>cf.iloc[-2]: u23=3
    elif cfv>0: u23=2
    elif cfv>-0.05: u23=1
    else: u23=0
    # Volume profile POC over last 120
    win=df.iloc[-120:] if n>=120 else df
    bins=np.linspace(win.low.min(),win.high.max(),25)
    tp2=((win.high+win.low+win.close)/3).values
    idx=np.clip(np.digitize(tp2,bins)-1,0,len(bins)-2)
    volhist=np.zeros(len(bins)-1)
    for i,vv in zip(idx,win.volume.values): volhist[i]+=vv
    poc=(bins[np.argmax(volhist)]+bins[np.argmax(volhist)+1])/2
    if px>poc*1.03: u24=3
    elif px>=poc*0.98: u24=2
    elif px>poc*0.95: u24=1
    else: u24=0
    avgv=v.rolling(20).mean().iloc[last]
    greenlast=df.close.iloc[last]>df.open.iloc[last]
    u25=1 if (v.iloc[last]>avgv*1.2 and greenlast) else 0
    # weekly volume trend
    wk=weekly(df)
    if wk is not None and len(wk)>=5:
        wv_now=wk.volume.iloc[-1]; wv_avg=wk.volume.iloc[-5:-1].mean()
        wgreen=wk.close.iloc[-1]>wk.open.iloc[-1]
        if wv_now>=1.5*wv_avg and wgreen: u26=2
        elif wv_now>=1.0*wv_avg and wgreen: u26=1
        elif wv_now<wv_avg or (wv_now>=1.5*wv_avg and not wgreen): u26=0
        else: u26=1
    else: u26=1
    volume=u20+u21+u22+u23+u24+u25+u26

    # ---- S/R (10)
    look=df.iloc[-60:] if n>=60 else df
    sh=look.high.max(); sl=look.low.min()
    sh_i=look.high.values.argmax(); sl_i=look.low.values.argmin()
    rng=(sh-sl) or 1e-9
    if sh_i>sl_i:  # uptrend swing, measure pullback from high
        retr=(sh-px)/rng
        bouncing=px>c.iloc[-4] if n>4 else True
        if 0.30<=retr<=0.65 and bouncing: sr27=5
        elif retr>0.786: sr27=0
        elif retr<0.20: sr27=3
        elif 0.20<=retr<=0.70: sr27=3
        else: sr27=2
    else:
        sr27=1 if px>(sl+0.382*rng) else 0
    # pivots from prior day
    ph,pl,pc_=df.high.iloc[-2],df.low.iloc[-2],df.close.iloc[-2]
    P=(ph+pl+pc_)/3; R1=2*P-pl; S1=2*P-ph
    if px>P and px<R1: sr28=4
    elif px>=R1: sr28=3
    elif px>S1: sr28=2
    else: sr28=0
    sr=sr27+sr28

    # ---- PATTERN (12)
    ewo=(sma(c,5)-sma(c,35))/c*100
    ewv=ewo.iloc[last]
    near_high=px>=look.high.iloc[:-1].max()*0.97
    if ewv>0 and ewo.iloc[last]>ewo.iloc[-3] and near_high: p29=5
    elif ewv>0 and ewo.iloc[last]>ewo.iloc[-3]: p29=3
    elif ewv>ewo.iloc[-3]: p29=2
    else: p29=0
    # zigzag swings (5% threshold)
    hh_ok,hl_ok=zigzag_structure(df)
    if hh_ok and hl_ok: p30=4
    elif hl_ok: p30=2
    else: p30=0
    rh=look.high.iloc[:-1].max()
    if px>rh and v.iloc[last]>avgv: p31=3
    elif px>rh*0.97: p31=2
    elif (look.high.iloc[-10:].max()-look.low.iloc[-10:].min())/px<0.08: p31=1
    else: p31=0
    pattern=p29+p30+p31

    # ---- SENTIMENT (7)
    pc_ratio=2  # neutral default (no options data)
    if spy_ret20 is not None:
        st_ret=(px/c.iloc[-21]-1) if n>21 else 0
        diff=st_ret-spy_ret20
        breadth=3 if diff>0.03 else (2 if diff>0 else (1 if diff>-0.03 else 0))
    else: breadth=1
    sentiment=pc_ratio+breadth

    cats={"trend":trend,"momentum":momentum,"volatility":volat,"volume":volume,
          "sr":sr,"pattern":pattern,"sentiment":sentiment}
    det.update({"ema20":e20.iloc[last],"rsi":rv,"vwap":vwap.iloc[last],
                "avgvol":avgv,"price":px})
    return cats, det

def zigzag_structure(df, thr=0.05):
    c=df.close.values
    piv=[]; last_p=c[0]; last_i=0; direction=0
    for i in range(1,len(c)):
        ch=(c[i]-last_p)/last_p
        if direction>=0 and ch<=-thr:
            piv.append((last_i,last_p,'H')); direction=-1; last_p=c[i]; last_i=i
        elif direction<=0 and ch>=thr:
            piv.append((last_i,last_p,'L')); direction=1; last_p=c[i]; last_i=i
        elif (direction>=0 and c[i]>last_p) or (direction<=0 and c[i]<last_p):
            last_p=c[i]; last_i=i
    highs=[p for p in piv if p[2]=='H']; lows=[p for p in piv if p[2]=='L']
    hh=len(highs)>=2 and highs[-1][1]>highs[-2][1]
    hl=len(lows)>=2 and lows[-1][1]>lows[-2][1]
    return hh,hl

def weekly(df):
    d=df.copy()
    d['date']=pd.to_datetime(d['date'])
    d=d.set_index('date')
    try:
        w=d.resample('W').agg({'open':'first','high':'max','low':'min',
                               'close':'last','volume':'sum'}).dropna()
        return w.reset_index()
    except Exception:
        return None

# ------------------------------------------------------------------ adjustments
def adjustments(df, cats, meta, weekly_raw):
    c=df.close; n=len(df); px=c.iloc[-1]
    e20=ema(c,20).iloc[-1]; r=rsi(c).iloc[-1]
    v=df.volume; avgv=v.rolling(20).mean().iloc[-1]
    items=[]; pen=0.0
    eps=meta.get('eps'); div=meta.get('div')
    loss_making = (eps is not None and eps<0)
    no_div = (div is None or div==0)

    # gains
    g5=(px/c.iloc[-6]-1)*100 if n>6 else 0
    g10=(px/c.iloc[-11]-1)*100 if n>11 else 0

    # R2 trend gate -> handled in caller (cap). flag here
    trend_cap = cats['trend']<8

    # R3 volume gate
    r3=0
    if cats['volume']<7: r3=-10; pen+=r3
    items.append(("R3 Volume gate", r3))

    # R4 RSI overbought
    r4=0
    if r>80: r4=-10; pen+=r4
    items.append(("R4 RSI>80", r4))

    # R5 post-breakout decay (CQ-C default ×1.0)
    base5=0
    if g5>=80: base5=-30
    elif g5>=50: base5=-20
    elif g5>=30: base5=-10
    r5=base5  # CQ-C
    pen+=r5
    items.append(("R5 Decay (CQ-C)", r5))

    # R6 extension + MHM
    ext=(px/e20-1)*100 if e20>0 else 0
    base6=0
    if ext>=40: base6=-15
    elif ext>=30: base6=-10
    elif ext>=20: base6=-5
    # MHM checks
    up_days=int((c.diff().iloc[-7:]>0).sum()) if n>7 else 0
    maxday=(c.pct_change().iloc[-7:].max()*100) if n>7 else 0
    mh1 = up_days>=3 and maxday<25
    medv=v.iloc[-7:].median() if n>7 else avgv
    mh2 = (v.iloc[-7:].max() < 3*medv) if medv>0 else False
    mh3 = r<75
    mh4 = (df.low.iloc[-3:].min() > df.low.iloc[-6:-3].min()) if n>6 else False
    passes=sum([mh1,mh2,mh3,mh4])
    r6=base6*[1.0,0.75,0.5,0.25,0.0][passes]
    pen+=r6
    items.append((f"R6 Extension (MHM {passes}/4)", round(r6,1)))

    # R8 divergence (price HH but oscillator LH on RSI/MFI/CCI/TSI/Stoch)
    div_count=count_divergences(df)
    r8=-10 if div_count>=2 else 0
    pen+=r8
    items.append((f"R8 Divergence x{div_count}", r8))

    # R9 distribution
    flags=[]
    d1 = g10>10  # small/mid cap rapid advance
    d2 = loss_making
    d3 = False
    # D4 weekly vol-conf divergence: weekly green but weekly obv slope down
    wk=weekly(df); d4=False
    if wk is not None and len(wk)>=6:
        wgreen=wk.close.iloc[-1]>wk.open.iloc[-1]
        wobv=slope((np.sign(wk.close.diff()).fillna(0)*wk.volume).cumsum().iloc[-6:])
        d4 = wgreen and wobv<0
    d5 = False
    d6 = True  # no catalyst data -> default no-catalyst
    # only count D6 if there's actually a rise to explain
    d6 = d6 and (g10>8)
    flags=[d1,d2,d3,d4,d5,d6]
    nf=sum(flags)
    r9=0
    if nf>=5: r9=-25
    elif nf==4: r9=-20
    elif nf==3: r9=-15
    pen+=r9
    items.append((f"R9 Distribution {nf}/6", r9))

    # R10 fundamental reality (loss + no div + (revenue unknown->treat weak))
    r10=0
    if loss_making and no_div: r10=-5
    pen+=r10
    items.append(("R10 Fundamentals", r10))

    # R14 Exhaustion Detection (v3 NEW) — compute before R19 for mutex
    r14_raw, ex_count = compute_exhaustion(df)
    # R19 Coiled Spring (v3 NEW) — compute early for mutex with R14
    r19_raw = compute_coiled_spring(df)
    # Mutex: if both fire, apply only the one with larger absolute value
    if r14_raw < 0 and r19_raw > 0:
        if abs(r14_raw) >= r19_raw:
            r14 = r14_raw; r19 = 0   # exhaustion dominates
        else:
            r14 = 0; r19 = r19_raw   # coiled spring dominates
    else:
        r14 = r14_raw; r19 = r19_raw
    if r14 < 0: pen += r14   # only penalties go into capped sum
    ex_flag = ("🛑 HIGH EXHAUSTION" if ex_count>=4 else
               ("⚠️ EXHAUSTION RISK" if ex_count>=3 else ""))
    items.append((f"R14 Exhaustion ({ex_count}/5)", r14))

    # R17 Close Position Signal (v3 NEW) — penalty goes into cap, bonus is post-cap
    r17 = compute_close_position(df)
    if r17 < 0: pen += r17
    items.append(("R17 Close Position", r17))

    # R18 Momentum Direction (v3 NEW) — same split
    r18 = compute_momentum_direction(df)
    if r18 < 0: pen += r18
    items.append(("R18 Mom Direction", r18))

    # R12 penalty cap (v3: covers R3-R6, R8-R10, R14, R17-, R18-)
    cap = -45 if (nf>=5 and r10<0) else -30
    capped = max(pen, cap)
    cap_adj = capped - pen
    items.append((f"R12 Cap ({cap})", round(cap_adj,1)))

    # Post-cap bonuses from R17/R18 (positive values only — exempt from cap)
    post_bonus = max(0, r17) + max(0, r18)

    # R13 MCT (active if base5<=-20)
    mct_active = base5<=-20
    mct=0; mct_detail=None
    if mct_active:
        mct=compute_mct(df)
        mct_detail=mct
    # MCT offsets penalty (reduces magnitude, doesn't flip positive beyond intent)
    total = capped + mct + post_bonus

    # R7 MTF bonus
    raw=sum(cats.values())
    r7=5 if (raw>=70 and weekly_raw>=70) else 0
    items.append(("R7 MTF bonus", r7))
    total += r7

    # R15 Volume Acceleration (v3, exempt from cap) — returned separately for score_ticker
    r15 = compute_volume_acceleration(df)
    items.append(("R15 Vol Accel", r15))
    items.append(("R19 Coiled Spring", r19))

    return {"items":items,"total":round(total,1),"trend_cap":trend_cap,
            "mct_active":mct_active,"mct":mct,"dist_flags":nf,
            "g5":round(g5,1),"g10":round(g10,1),"ext":round(ext,1),"rsi":round(r,1),
            "r15":r15,"r19":r19,"ex_count":ex_count,"ex_flag":ex_flag}

def count_divergences(df):
    c=df.close
    if len(c)<20: return 0
    recent=c.iloc[-12:]; prev=c.iloc[-24:-12] if len(c)>=24 else c.iloc[:-12]
    price_hh = recent.max()>prev.max()
    if not price_hh: return 0
    cnt=0
    for ind in [rsi(c), mfi(df), cci(df), tsi(c)[0]]:
        rr=ind.iloc[-12:].max(); pp=ind.iloc[-24:-12].max() if len(ind)>=24 else ind.iloc[:-12].max()
        if rr<pp: cnt+=1
    k,_=stoch(df)
    if k.iloc[-12:].max()< (k.iloc[-24:-12].max() if len(k)>=24 else k.iloc[:-12].max()): cnt+=1
    return cnt

def compute_mct(df):
    c=df.close; v=df.volume; n=len(df)
    # MCT1 volume trend quality: vol up on up-legs, down on pullbacks
    chg=c.diff().iloc[-5:]; vol=v.iloc[-5:]
    up_v=vol[chg>0].mean() if (chg>0).any() else 0
    dn_v=vol[chg<0].mean() if (chg<0).any() else 0
    spike = v.iloc[-5:].max() > 3*v.iloc[-20:].median() if n>20 else False
    if up_v>dn_v and not spike: mct1=5
    elif up_v>dn_v: mct1=3
    elif not spike: mct1=2
    else: mct1=0
    # MCT2 pullback structure
    pulls=(c.diff().iloc[-7:]<0).sum()
    held = df.low.iloc[-3:].min()>df.low.iloc[-7:-3].min() if n>7 else False
    if pulls>=1 and held: mct2=4
    elif pulls>=1: mct2=2
    else: mct2=0
    # MCT3 candle quality (small wicks, solid bodies)
    body=(df.close-df.open).abs().iloc[-5:]
    rng=(df.high-df.low).iloc[-5:].replace(0,np.nan)
    bodyratio=(body/rng).mean()
    mct3=3 if bodyratio>0.6 else (2 if bodyratio>0.45 else (1 if bodyratio>0.3 else 0))
    mct4=0  # catalyst (no news data)
    mct5=0  # institutional (no 13F/options data)
    return int(mct1+mct2+mct3+mct4+mct5)

ZONES=[(85,"Elite","Full conviction"),(70,"Strong","Enter w/ confidence"),
       (55,"Moderate","Enter w/ caution"),(40,"Weak","Watchlist only"),
       (25,"Poor","Stay away"),(0,"Broken","Avoid/exit")]
def zone_of(score):
    for thr,name,act in ZONES:
        if score>=thr: return name,act
    return "Broken","Avoid"

# ------------------------------------------------------------------ per-ticker
def score_ticker(code, meta, spy_ret20):
    df=fetch_eod(code)
    if df is None or len(df)<60: return None
    df=df[['date','open','high','low','close','volume']].dropna()
    df=df[df.close>0]
    if len(df)<60: return None
    df=df.reset_index(drop=True)
    try:
        cats,det=score_categories(df,spy_ret20)
        # R16 Days-Since-Breakout Decay: apply to Category 6 Pattern BEFORE raw sum
        decay=compute_breakout_decay(df)
        if decay<1.0:
            cats['pattern']=int(cats['pattern']*decay)
        wk=weekly(df)
        weekly_raw=0
        if wk is not None and len(wk)>=30:
            wc,_=score_categories(wk.reset_index(drop=True),spy_ret20)
            weekly_raw=sum(wc.values())
        adj=adjustments(df,cats,meta,weekly_raw)
        raw=sum(cats.values())
        final=raw+adj['total']
        if adj['trend_cap']: final=min(final,50)
        # R15 Volume Acceleration + R19 Coiled Spring (exempt from R12 cap)
        final+=adj.get('r15',0)+adj.get('r19',0)
        final=max(0,min(100,final))
        zone,action=zone_of(final)
        if adj['mct_active'] and adj['mct']>=15:
            action="MCT: "+action+" (1-level up)"
        if adj.get('r19',0)>=5:
            action="🔥 COILED: "+action
        if adj.get('ex_flag',''):
            action=adj['ex_flag']+": "+action
        return {"code":code,"name":meta.get('name',''),"price":round(det['price'],3),
                "trend":cats['trend'],"momentum":cats['momentum'],"volatility":cats['volatility'],
                "volume":cats['volume'],"sr":cats['sr'],"pattern":cats['pattern'],
                "sentiment":cats['sentiment'],"raw":raw,"adj":adj['total'],
                "final":round(final,1),"zone":zone,"action":action,
                "weekly_raw":weekly_raw,"g5":adj['g5'],"g10":adj['g10'],
                "ext":adj['ext'],"rsi":adj['rsi'],"dist_flags":adj['dist_flags'],
                "mct":adj['mct'] if adj['mct_active'] else "",
                "sector":meta.get('sector',''),"mcap":meta.get('mcap',''),
                "avgvol":meta.get('avgvol','')}
    except Exception as e:
        return {"code":code,"error":str(e)[:80]}

def get_spy_ret20():
    df=fetch_eod("SPY.US")
    if df is None: return 0.0
    c=df['close']
    return c.iloc[-1]/c.iloc[-21]-1

# ------------------------------------------------------------------ chunked run
PARTS=os.path.join(HERE,"parts")
os.makedirs(PARTS,exist_ok=True)

def run_chunk(offset, limit, workers=16):
    uni=pd.read_csv(os.path.join(HERE,"universe.csv"))
    chunk=uni.iloc[offset:offset+limit]
    spy=get_spy_ret20()
    metas={}
    for _,row in chunk.iterrows():
        metas[row['code']]={"name":row.get('name'),"eps":_num(row.get('earnings_share')),
            "div":_num(row.get('dividend_yield')),"sector":row.get('sector'),
            "mcap":row.get('market_capitalization'),"avgvol":row.get('avgvol_200d')}
    results=[]; errors=0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(score_ticker,code,metas[code],spy):code for code in metas}
        for fu in as_completed(futs):
            try:
                res=fu.result()
            except Exception as e:
                errors+=1; continue
            if res is None or 'error' in res: errors+=1
            else: results.append(res)
    with open(os.path.join(PARTS,f"part_{offset:05d}.json"),"w",encoding="utf-8") as f:
        json.dump(results, f, default=_jsonify)
    print(f"chunk {offset}-{offset+limit}: {len(results)} scored, {errors} skipped")
    return len(results),errors

def combine():
    rows=[]
    for fn in sorted(os.listdir(PARTS)):
        if fn.startswith("part_") and fn.endswith(".json"):
            rows+=json.load(open(os.path.join(PARTS,fn),encoding="utf-8"))
    # dedupe by code keep first
    seen=set(); uniq=[]
    for r in rows:
        if r['code'] in seen: continue
        seen.add(r['code']); uniq.append(r)
    uniq.sort(key=lambda x:-x['final'])
    out=os.path.join(HERE,"scored_ranked.csv")
    cols=["rank","code","name","sector","price","mcap","avgvol","trend","momentum",
          "volatility","volume","sr","pattern","sentiment","raw","adj","final","zone",
          "action","weekly_raw","g5","g10","ext","rsi","dist_flags","mct"]
    with open(out,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore")
        w.writeheader()
        for i,r in enumerate(uniq,1):
            r['rank']=i; w.writerow(r)
    print(f"COMBINED: {len(uniq)} tickers -> {out}")
    return len(uniq)

def _num(x):
    try:
        if x is None or (isinstance(x,float) and math.isnan(x)): return None
        return float(x)
    except Exception: return None

def _jsonify(obj):
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    raise TypeError(f"Not serializable: {type(obj)}")

if __name__=="__main__":
    import sys
    if len(sys.argv)>1 and sys.argv[1]=="chunk":
        run_chunk(int(sys.argv[2]), int(sys.argv[3]))
    elif len(sys.argv)>1 and sys.argv[1]=="combine":
        combine()
    else:
        run_chunk(0, 999999)
