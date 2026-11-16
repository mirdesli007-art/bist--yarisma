"""BIST hisse evreni ve şirket adı eşleştirmeleri (haber -> hisse)."""

BIST100 = """
AEFES AGHOL AHGAZ AKBNK AKSA AKSEN ALARK ALFAS ALTNY ANSGR ARCLK ASELS ASTOR
BALSU BERA BIMAS BINHO BRSAN BRYAT BSOKE BTCIM CANTE CCOLA CIMSA CLEBI CWENE
DOAS DOHOL DSTKF ECILC EGEEN EKGYO ENERY ENJSA ENKAI EREGL EUPWR FENER
FROTO GARAN GENIL GESAN GLRMK GRSEL GRTHO GSRAY GUBRF HALKB HEKTS IEYHO 
ISCTR ISMEN KARSN KCAER KCHOL KONTR KRDMD KTLEV KUYAS LMKDC MAGEN
MAVI MGROS MIATK MPARK OBAMS ODAS OTKAR OYAKC PASEU PATEK PETKM PGSUS QUAGR
RALYH REEDR SAHOL SASA SISE SKBNK SMRTG SOKM TABGD TAVHL TCELL THYAO TKFEN
TOASO TRALT TRENJ TRMET TSKB TSPOR TTKOM TTRAK TUKAS TUPRS TURSG ULKER
VAKBN VESTL YEOTK YKBNK ZOREN
""".split()

INDEXES = {"BIST 100": "XU100.IS", "BIST 30": "XU030.IS", "Bankacılık": "XBANK.IS"}
MACRO = {"USD/TRY": "USDTRY=X", "EUR/TRY": "EURTRY=X", "Brent": "BZ=F", "Altın (ons)": "GC=F"}

# Haber başlıklarında geçen şirket adlarını hisse koduna bağlar
NAMES = {
    "THYAO": ["THY", "Türk Hava Yolları", "Turkish Airlines"],
    "PGSUS": ["Pegasus"],
    "ASELS": ["Aselsan"],
    "TUPRS": ["Tüpraş"],
    "EREGL": ["Erdemir"],
    "KRDMD": ["Kardemir"],
    "BIMAS": ["BİM", "Bim Birleşik"],
    "MGROS": ["Migros"],
    "SOKM": ["Şok Market"],
    "GARAN": ["Garanti BBVA", "Garanti Bankası"],
    "AKBNK": ["Akbank"],
    "ISCTR": ["İş Bankası", "İşbank"],
    "YKBNK": ["Yapı Kredi"],
    "HALKB": ["Halkbank"],
    "VAKBN": ["Vakıfbank", "VakıfBank"],
    "KCHOL": ["Koç Holding"],
    "SAHOL": ["Sabancı"],
    "FROTO": ["Ford Otosan"],
    "TOASO": ["Tofaş"],
    "ARCLK": ["Arçelik", "Beko"],
    "VESTL": ["Vestel"],
    "SISE": ["Şişecam"],
    "TCELL": ["Turkcell"],
    "TTKOM": ["Türk Telekom"],
    "PETKM": ["Petkim"],
    "SASA": ["SASA"],
    "HEKTS": ["Hektaş"],
    "ENKAI": ["Enka"],
    "TAVHL": ["TAV Havalimanları", "TAV "],
    "EKGYO": ["Emlak Konut"],
    "ASTOR": ["Astor Enerji"],
    "AEFES": ["Anadolu Efes"],
    "CCOLA": ["Coca-Cola İçecek"],
    "ULKER": ["Ülker"],
    "OTKAR": ["Otokar"],
    "DOAS": ["Doğuş Otomotiv"],
    "TTRAK": ["Türk Traktör"],
    "GUBRF": ["Gübre Fabrikaları", "Gübretaş"],
    "ALARK": ["Alarko"],
    "ENJSA": ["Enerjisa"],
    "TKFEN": ["Tekfen"],
    "MAVI": ["Mavi Giyim"],
    "FENER": ["Fenerbahçe"],
    "GSRAY": ["Galatasaray"],
    "TSPOR": ["Trabzonspor"],
    "CIMSA": ["Çimsa"],
    "OYAKC": ["Oyak Çimento"],
    "TABGD": ["TAB Gıda", "Burger King"],
    "MPARK": ["MLP Sağlık", "Medical Park"],
    "DOHOL": ["Doğan Holding"],
    "AGHOL": ["Anadolu Grubu"],
    "TURSG": ["Türkiye Sigorta"],
    "ANSGR": ["Anadolu Sigorta"],
    "KONTR": ["Kontrolmatik"],
    "MIATK": ["Mia Teknoloji"],
    "PASEU": ["Pasifik Eurasia"],
}


def yahoo(sym: str) -> str:
    return sym if "." in sym or "=" in sym else f"{sym}.IS"


def plain(sym: str) -> str:
    return sym.replace(".IS", "")
