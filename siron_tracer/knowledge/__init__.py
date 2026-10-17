"""Siron AML research: what is known about Siron's tables, organised for the app.

The full research text ships as ``siron_aml_arastirma.md``. This module holds the
same findings in structured form so the app can

* group tables into Siron modules by name prefix (``classify``),
* show the research note for a table it actually finds in the schema,
* explain German column names (KUNDNR, HISTBIS, ...) with ``explain``,
* offer the research's verification queries for the current schema.

Confidence levels follow the research: ``verified`` = seen in real Siron SQL or an
official interface, ``likely`` = consistent expansion within a documented module,
``guess`` = plausible expansion only, ``unresolved`` = no defensible reading.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DOC_PATH = os.path.join(os.path.dirname(__file__), "siron_aml_arastirma.md")
DOC_TITLE = "Siron AML metadata ve tablolar araştırması"

CONFIDENCE = {"verified": "Doğrulanmış", "likely": "Olası", "guess": "Tahmin", "unresolved": "Çözülmemiş"}
CONFIDENCE_HELP = {
    "verified": "Tablo/alan adı gerçek Siron SQL'inde veya resmi bir arayüzde görüldü.",
    "likely": "Almanca/İngilizce açılım tutarlı ve kaynaklı bir modül tanımına oturuyor.",
    "guess": "Yalnızca makul bir açılım; veritabanında doğrulanmalı.",
    "unresolved": "Savunulabilir bir okuma yok.",
}
CONFIDENCE_ORDER = ["verified", "likely", "guess", "unresolved"]


def load_document() -> str:
    with open(DOC_PATH, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------- modules

@dataclass
class Module:
    id: str
    name: str
    product: str
    summary: str
    icon: str = "layers"
    short: str = ""


MODULES: List[Module] = [
    Module("aml", "AML çekirdeği: konfigürasyon ve ana veri", "Siron AML (eski adı Siron GwG)",
           "Müşteri, hesap, işlem, ülke, para birimi, kullanıcı/rol, gösterge (Indiz), dahil/hariç listeleri, "
           "puanlama ve müşteri kategorileri. GwG = Geldwäschegesetz (Alman kara para aklama yasası).", "db", "AML çekirdeği"),
    Module("aml_result", "AML analiz ve alarm sonuçları", "Siron AML",
           "Puanlama ve analiz sonuçları, işlem isabetleri (Treffer = alarm), dönemler, CSV raporları.", "zap", "AML sonuçları"),
    Module("aml_case", "AML ortak ana veri ve şüpheli vaka (SAR)", "Siron AML",
           "Kimlik belgesi, hukuki şekil, meslek, banka kodu, ilişkiler ile şüpheli vaka (Verdachtsfall), "
           "öncül suç, bildirim, mektup ve form şablonları. KYC'ye ait değildir.", "alert", "AML vaka (SAR)"),
    Module("kyc", "KYC: müşteri kabul, ad tarama, risk sınıfı", "Siron KYC (2011)",
           "KYC müşteri tablosu, liste kopyaları, ad eşanlamlıları ve isabetleri, işlem talimatları, kontrol "
           "protokolü, belgeler.", "user", "KYC"),
    Module("kyc_result", "KYC skor sonuçları ve PEP/ad tarama", "Siron KYC / Embargo-N",
           "Müşteri başına KYC risk sonucu (PRESULT), isabetler, tarama listesi setleri, kişi durumu.", "target", "KYC skor / PEP"),
    Module("questionnaire", "KYC anket çerçevesi", "Siron KYC",
           "Anket formları, sorular, cevaplar ve tarihçesi, anket iş akışı ağacı ve açık adımlar.", "list", "KYC anket"),
    Module("lists", "Yaptırım ve izleme listeleri", "Embargo / KYC (ortak)",
           "Yaptırım/PEP listelerinin ortak deposu: isimler, adresler, doğum, pasaport, uyruk, ilişkiler, "
           "liste sürüm tarihi. Embargo ve KYC aynı listeleri paylaşır.", "shield", "Yaptırım listeleri"),
    Module("embargo", "Embargo: ödeme taraması", "Siron Embargo",
           "SWIFT/SEPA ödeme taraması: karar tablosu, liste tarihi, ödeme sistemi kuralları, stop-word listeleri.", "lock", "Embargo"),
    Module("tcr", "TCR: FATCA / CRS vergi raporlaması", "Siron TCR",
           "FATCA/CRS sınıflandırma ve raporlama: müşteri, hesap, ödeme, rapor şablonları, TaxAct vakaları. "
           "\"FA\" soneki FATCA demektir (KBRFA, KCOCFA, KSTATFA).", "file", "TCR (FATCA/CRS)"),
    Module("acm", "Alert & Case Manager (ACM)", "Siron ACM (~2018)",
           "Alarm ve vaka yönetimi: vakalar, iş akışları, süreç adımları, kullanıcı işlemleri, yetkiler.", "activity", "ACM"),
    Module("platform", "Tonbeller platformu ve referans listeleri", "Tüm modüllerin ortak altyapısı",
           "Kod listeleri (TBRLIST/TBRLEINT: kodların anlamını veren tablo), giriş kayıtları, parametreler, "
           "şube, risk sınıfları, yama geçmişi, arayüz metinleri. Uygulama seviyesi veri sözlüğü adayları "
           "(TBDEF, TBBO, TBFELDZ, TBDOMAIN...) burada.", "settings", "Platform (TB)"),
    Module("reporting", "Siron TDI raporlama katmanı", "Siron TDI (web OLAP/raporlama)",
           "TDI'nin rapor/navigatör deposu, paket üretici ve kilit tabloları. İçe aktarım arayüzü değildir.", "chart", "TDI raporlama"),
    Module("ras", "Kurum risk analizi (RAS / RCC)", "Siron RAS / RCC",
           "Gefährdungsanalyse: risk matrisi ana verisi, göstergeler, kategoriler, toplamlar.", "pie", "RAS / RCC"),
    Module("masak", "Yerel MASAK köprüsü", "Bankaya özgü (vendor şeması değil)",
           "Siron ile MASAK ŞİB raporlaması arasına banka/uygulayıcı tarafından kurulan eşleme ve kod tabloları. "
           "Vendor dokümantasyonu beklenmemeli; bilgisi uyum biriminde.", "link", "MASAK köprüsü"),
    Module("unknown", "Çözülmemiş aileler", "Belirsiz",
           "Açılımı bulunamayan önekler (MM*, WS*). Veritabanında içerik ve kullanım ile çözülmeli.", "info", "Çözülmemiş"),
]
MODULE_BY_ID = {m.id: m for m in MODULES}


# --------------------------------------------------------------------------- prefix families

@dataclass
class Family:
    prefix: str             # label shown to users, e.g. "GWG*"
    module: str
    meaning: str
    confidence: str
    pattern: str            # regex matched against the upper-case table name
    examples: Tuple[str, ...] = ()
    regex: "re.Pattern" = field(init=False, repr=False)

    def __post_init__(self):
        self.regex = re.compile(self.pattern)


# Order matters: the first matching family wins (specific before generic).
FAMILIES: List[Family] = [
    Family("PARAM_* / MASAK_* / BANK_2_MASAK_*", "masak",
           "Bankanın MASAK ŞİB kod listelerine kurduğu köprü: form alanı → Siron sütunu eşlemesi, iç kod → MASAK kodu.",
           "likely", r"^(PARAM_|MASAK_|BANK_2_MASAK)", ("MASAK_2_SIRON_FIELD_MAP", "BANK_2_MASAK_CODE", "PARAM_MESLEK", "PARAM_ULKEKODU")),
    Family("SIBFORM / LOCKEDSIBFORMS", "masak",
           "\"SIB\" = Şüpheli İşlem Bildirimi okuması güçlü ama kanıtsız; ACM'nin genel bildirim formu altyapısı da olabilir.",
           "guess", r"^(LOCKED)?SIBFORMS?$", ("SIBFORM", "LOCKEDSIBFORMS")),
    Family("CASEFLAG* / FARCASEFLAG*", "tcr", "TaxAct (FATCA) vaka bayrakları.", "likely",
           r"^(FAR)?CASEFLAG", ("CASEFLAG", "FARCASEFLAG")),
    Family("CACM* / CASE* / WORKFLOW* / PROCESSSTEP*", "acm",
           "ACM'nin İngilizce adlı tabloları: yapılandırılabilir iş akışları, çok seviyeli onay, kullanıcı işlem izi.",
           "likely", r"^(CACM|CASE|WORKFLOW|PROCESSSTEP|ACTIVITYENTRY|USERAUTH|USRSTTNG)",
           ("CACM...", "CASE...", "WORKFLOW...", "PROCESSSTEP...", "ACTIVITYENTRY", "USERAUTH", "USRSTTNG")),
    Family("FAR* / TAX* / NOINDICIA*", "tcr",
           "FATCA/CRS raporlaması. FAR = büyük olasılıkla \"FATCA (Account) Reporting\"; açılım bulunamadı.",
           "likely", r"^(FAR|TAX|NOINDICIA)",
           ("FARCUSTOMER", "FARACCOUNT", "FARPAYMENT", "FARREPORT", "TAXACTCASE", "NOINDICIACUSTOMER")),
    Family("K*FA", "tcr", "KYC modülündeki FATCA tabloları: \"FA\" soneki FATCA (KBRFA, KCOCFA, KSTATFA).", "verified",
           r"^K[A-Z]{2,6}FA$", ("KBRFA", "KCOCFA", "KSTATFA")),
    Family("TBQ*", "questionnaire", "Q = Questionnaire: formlar, sorular, cevaplar, iş nesneleri, iş akışı ağacı.",
           "likely", r"^TBQ", ("TBQFORMS", "TBQQUEST", "TBQANSW", "TBQANSWH", "TBQWKFLTREE", "TBQWKFLOPENSTEPS")),
    Family("TDI*", "reporting", "Siron TDI raporlama katmanının kendi deposu (REPOS), paket üretici, kilit.", "likely",
           r"^TDI", ("TDIREPOS", "TDIPKGEN", "TDILOCK")),
    Family("TB*", "platform",
           "TonBeller platform/çerçeve tabloları. TBRLIST/TBRLEINT kod listeleri doğrulanmış; veri sözlüğü taşıyıcısı "
           "olma iddiası (TBDEF, TBFELDZ, TBDOMAIN...) hipotez.",
           "likely", r"^TB", ("TBRLIST", "TBRLEINT", "TBPARA", "TBDOMAIN", "TBDOMVAL", "TBFILIAL", "TBPATCH", "TBRIKLAS")),
    Family("GWG*", "aml", "GwG = Geldwäschegesetz. Kunde, Konto, Transaktion, Land, Währung, Parameter, Benutzer, Rolle, "
           "Indiz, Inklusion/Exklusion, Scores, Kategorie, Feld.", "likely", r"^GWG",
           ("GWGKUNDE", "GWGKONTO", "GWGTRANS", "GWGLAND", "GWGWAE", "GWGIND", "GWGKAT", "GWGINKL", "GWGEXKL")),
    Family("GWA*", "aml_result", "\"A\" = Analyse/Auswertung (tahmin). TRHIT = işlem isabeti (alarm), SCORE = hesaplanan puan.",
           "likely", r"^GWA", ("GWAKUNDE", "GWASCORE", "GWATRHIT", "GWATRHITANA", "GWAZEIT", "GWARCSV")),
    Family("SL_*", "lists", "SL = Sanctions/Screening List. WLDATE = watch-list sürüm tarihi.", "likely", r"^SL_",
           ("SL_MAIN", "SL_NAMES", "SL_ADDR", "SL_BIRTH", "SL_PASS", "SL_CITIZ", "SL_RELATIONS", "SL_WLDATE")),
    Family("GB_* / RB_*", "ras", "GB = Gefährdungsbeurteilung?, RB = Risikobewertung?; STM = Stamm, IND = Indikator, KAT = Kategorie.",
           "guess", r"^(GB|RB)_", ("GB_STM", "GB_IND", "GB_KAT", "RB_INM", "RB_STM", "RB_BWZ")),
    Family("KSL* / K*", "kyc", "KYC: KSL = KYC'nin liste kopyası, Synonym = ad varyantı, Handlungsanweisung = işlem talimatı.",
           "likely", r"^K", ("KYCCUST", "KSLMAIN", "KSYNONYM", "KSYNONYMHIT", "KRESULT", "KHANDANW", "KCKPROT")),
    Family("P*", "kyc_result", "KYC skorlama/profil sonuç katmanı + PEP/ad tarama. PRESULT doğrulanmış.", "likely",
           r"^(PEP|PHIT|PRESULT|PSL|PDOC|PFLD|PERSSTAT)", ("PRESULT", "PRESULT_ARCHIVE", "PHIT", "PSLSET", "PEPPARAM", "PERSSTAT")),
    Family("E* / EMB*", "embargo", "Embargo: DECTAB = karar tablosu, WLDATE = liste tarihi, PAYSYSR = ödeme sistemi kuralı, SW = stop words.",
           "likely", r"^(EMB|EDECTAB|EWLDATE|EPAYSYS|ESW|EPRPE|EBRPE)", ("EMBINST", "EMBLOCK", "EDECTAB", "EWLDATE", "EPAYSYSR", "ESW")),
    Family("C*", "aml_case", "Ortak ana veri + şüpheli vaka katmanı. \"C\"nin açılımı (Common/Core/Compliance) bilinmiyor.",
           "likely", r"^C(KUNDE|KONTO|TRANS|ADDR|RELA|AUSW|CITIZ|BLZ|RECHTF|BERUF|VORFALL|VORTAT|VFA|ANZ|BRIEF|SBRIEF|TXTBAU|DRKFORM|ZVF|VST|EKRIT|ARINST)",
           ("CKUNDE", "CKONTO", "CTRANS", "CADDR", "CRELAT", "CAUSWEIS", "CVORFALL", "CANZEIGE", "CBRIEF")),
    Family("MM*", "unknown", "Nachricht = mesaj (olası); \"MM\" = Marktmissbrauch mı, Message Manager mı bilinmiyor.",
           "unresolved", r"^MM", ("MMNACHR", "MMNACHRZ")),
    Family("WS*", "unknown", "Web servis durum/kilit tabloları olabilir.", "guess", r"^WS(STATUS|LOCK)", ("WSSTATUS", "WSLOCK")),
]


# --------------------------------------------------------------------------- known tables

@dataclass
class KnownTable:
    name: str
    module: str
    meaning: str
    expansion: str = ""
    confidence: str = "likely"
    note: str = ""


def _t(name, module, meaning, expansion="", confidence="likely", note=""):
    return KnownTable(name, module, meaning, expansion, confidence, note)


KNOWN_TABLES: List[KnownTable] = [
    # verified in real Siron SQL / official WSDL
    _t("KYCCUST", "kyc", "Siron KYC müşteri ana tablosu", "KYC Customer", "verified",
       "Sütunlar: INSTITUTSNR, KUNDNR, HISTBIS, KYC_VORNAME, KYC_NACHNAME, KYC_SP_01…32 (kuruma göre eşlenen serbest "
       "alanlar: örnek kurulumda SP_01 cinsiyet, SP_02 dil, SP_03 sektör, SP_04 unvan, SP_32 şube), RISIKO."),
    _t("PRESULT", "kyc_result", "Müşteri başına KYC risk sınıflandırma/skorlama sonucu", "Profil/Prüf-Result", "verified",
       "Sütunlar: INSTITUTSNR, KUNDNR, HISTBIS, ERFASSER (kaydı giren), RISIKO (risk sınıfı)."),
    _t("TBRLEINT", "platform", "Kod listesi girdileri: kodların anlamını veren tablo", "Referenzlisten-Einträge", "verified",
       "RL_KUERZEL = liste kodu, BEZ = kod değeri, KOMMENTAR = açıklama, HISTBIS='9999' güncel kayıt. "
       "KYC_SP_04 gibi kod alanları TBRLEINT.KOMMENTAR ile açıklamaya çevrilir. Örnek kurulumda GLOBAL şemasında."),
    _t("TBRLIST", "platform", "Kod listesi başlıkları (referans listeleri)", "Referenzlisten", "verified"),
    _t("TBRLISTFIELD", "platform", "Referans listesi alan tanımları", "Referenzliste Feld"),
    _t("TBRLEINTFIELD", "platform", "Referans listesi girdisi alan tanımları", "Referenzlisten-Eintrag Feld"),
    _t("GWGKUSY", "aml", "Müşteri sistematiği (KuSy), müşteri sınıflandırma alanı", "Kundensystematik", "likely",
       "WSDL'deki PersonData.cusy ve 2003 whitepaper'daki KuSy ile örtüşüyor; kavram doğrulanmış."),
    _t("CRELAT", "aml_case", "Müşteri ilişkileri (gerçek faydalanıcı dahil)", "Relation", "likely", "WSDL BoData: boKundnr, kundnr, relType, share."),
    _t("CRELART", "aml_case", "İlişki türleri", "Relationsart"),
    _t("TBRIKLAS", "platform", "Risk sınıfları", "Risikoklasse", "likely", "WSDL KycRisk: riskAbbrev, riskClass, riskDesc."),
    _t("KHANDANW", "kyc", "Müşteri temsilcisine işlem talimatları (sıralı)", "Handlungsanweisung", "likely",
       "WSDL KycActions: shortText, longText, rang."),
    _t("KCKPROT", "kyc", "KYC kontrol protokolü (PDF)", "Check-Protokoll", "likely", "WSDL kycGetPdfProtocol."),
    _t("KSYNONYMHIT", "kyc", "Ad eşanlamlısı tarama isabetleri", "Synonym-Treffer"),
    _t("KSYNONYM", "kyc", "Ad varyantları / eşanlamlılar", "Synonym", "guess"),
    _t("KSLMAIN", "kyc", "KYC'nin yaptırım listesi kopyası (ana kayıt)", "KYC Sanctions List", "guess"),
    _t("KRESULT", "kyc", "KYC tarama sonucu", "Result", "guess"),
    _t("KBRFA", "tcr", "KYC FATCA iş kuralları", "KYC Business Rules FATCA", "likely", "WSDL BusinessRuleResult: brId, brAction."),
    _t("KCOCFA", "tcr", "FATCA durum değişikliği kayıtları", "Change of Circumstances FATCA", "likely",
       "WSDL ChangeOfCircumstances: cocType, cocText, histVon, histBis."),
    _t("KSTATFA", "tcr", "FATCA durum tablosu", "Status FATCA", "likely"),
    _t("TAXACTCASE", "tcr", "TaxAct (FATCA) vakaları", "Tax Act Case", "likely", "WSDL TaxActResult01: caseFlags, caseStatus."),
    _t("FARCUSTOMER", "tcr", "FATCA/CRS raporlama müşterisi", "FATCA Account Reporting Customer", "guess"),
    _t("FARACCOUNT", "tcr", "FATCA/CRS raporlama hesabı", "", "guess"),
    _t("NOINDICIACUSTOMER", "tcr", "FATCA göstergesi (indicia) olmayan müşteriler", "", "likely"),
    _t("DOCUMENTTYPE", "kyc", "Belge türleri", "", "likely", "WSDL DocumentTypeData01: typeNr, name, followUpLeadDays."),
    _t("ATTACHMENT", "kyc", "Müşteri belgeleri / ekler", "", "likely"),
    _t("PDOC", "kyc_result", "Kişi belgeleri", "Personen-Dokument", "guess"),
    _t("TBQWKFLOPENSTEPS", "questionnaire", "Anket iş akışının açık adımları", "Questionnaire Workflow Open Steps", "likely",
       "WSDL WorkFlowStatus01.existsOpenWorkFlowSteps."),
    _t("TBQFORMS", "questionnaire", "Anket formları", "", "likely"),
    _t("TBQQUEST", "questionnaire", "Anket soruları", "", "likely"),
    _t("TBQANSW", "questionnaire", "Anket cevapları", "", "likely"),
    _t("TBQANSWH", "questionnaire", "Anket cevap tarihçesi", "", "likely"),
    _t("TBQWKFLTREE", "questionnaire", "Anket iş akışı ağacı", "", "likely"),
    _t("TDIREPOS", "reporting", "TDI rapor/navigatör deposu (tablo/alan metaverisi içerebilir)", "TDI Repository", "likely"),
    _t("TDIPKGEN", "reporting", "TDI paket üretici", "Package Generator", "likely"),
    _t("TDILOCK", "reporting", "TDI çalıştırma kilidi", "", "likely"),
    # AML core (GWG)
    _t("GWGKUNDE", "aml", "AML müşteri ana verisi", "Kunde", "likely"),
    _t("GWGKONTO", "aml", "AML hesap ana verisi", "Konto", "likely"),
    _t("GWGTRANS", "aml", "AML işlemleri", "Transaktion", "likely"),
    _t("GWGLAND", "aml", "Ülkeler", "Land", "likely"),
    _t("GWGWAE", "aml", "Para birimleri", "Währung", "likely"),
    _t("GWGPARA", "aml", "AML parametreleri", "Parameter", "likely"),
    _t("GWGBENUT", "aml", "AML kullanıcıları", "Benutzer", "likely"),
    _t("GWGROLLE", "aml", "AML rolleri", "Rolle", "likely"),
    _t("GWGIND", "aml", "Göstergeler (AML tespit kuralları)", "Indiz", "likely", "Almanca AML jargonunda \"Indizien und Schwellenwerte\"."),
    _t("GWGINKL", "aml", "İzlemeye dahil listesi", "Inklusion", "likely"),
    _t("GWGEXKL", "aml", "İzlemeden hariç listesi", "Exklusion", "likely"),
    _t("GWGSCORS", "aml", "Puanlama tanımları", "Scores", "likely"),
    _t("GWGKAT", "aml", "Müşteri kategorileri (SironProfile mirası)", "Kategorie", "likely"),
    _t("GWGFELD", "aml", "Alan tanımları (uygulama sözlüğü adayı)", "Feld", "guess"),
    _t("GWGFTEXT", "aml", "Alan etiketleri (uygulama sözlüğü adayı)", "Feldtext", "guess"),
    _t("GWGGENKEY", "aml", "Üretilmiş anahtarlar", "Generated key", "likely"),
    _t("GWGNCCT", "aml", "FATF işbirliği yapmayan ülke ve bölgeler", "Non-Cooperative Countries and Territories", "likely"),
    _t("GWGSETUP", "aml", "AML kurulum ayarları", "Setup", "guess"),
    _t("GWGMRISK", "aml", "Çözülmemiş", "", "unresolved"),
    _t("GWGCCKU", "aml", "Çözülmemiş", "", "unresolved"),
    _t("GWGBUTAA", "aml", "Çözülmemiş", "", "unresolved"),
    _t("GWGPRCKU", "aml", "Çözülmemiş", "", "unresolved"),
    # AML results (GWA)
    _t("GWATRHIT", "aml_result", "İşlem isabetleri (alarmlar)", "Transaktions-Treffer", "likely"),
    _t("GWATRHITANA", "aml_result", "İşlem isabeti analizi", "Treffer-Analyse", "likely"),
    _t("GWASCORE", "aml_result", "Hesaplanan puanlar", "Score", "likely"),
    _t("GWAKUNDE", "aml_result", "Müşteri analiz sonuçları", "Kunde (Analyse)", "guess"),
    _t("GWAZEIT", "aml_result", "Analiz dönemleri", "Zeit", "guess"),
    _t("GWARCSV", "aml_result", "CSV raporları", "Report CSV", "guess"),
    # common master data / SAR (C)
    _t("CKUNDE", "aml_case", "Müşteri (ortak ana veri)", "Kunde", "likely"),
    _t("CKONTO", "aml_case", "Hesap (ortak ana veri)", "Konto", "likely"),
    _t("CTRANS", "aml_case", "İşlem (ortak ana veri)", "Transaktion", "likely"),
    _t("CADDR", "aml_case", "Adresler", "Address", "likely"),
    _t("CAUSWEIS", "aml_case", "Kimlik belgeleri", "Ausweis", "likely"),
    _t("CAUSWART", "aml_case", "Kimlik belgesi türleri", "Ausweisart", "likely"),
    _t("CCITIZ", "aml_case", "Vatandaşlık / uyruk", "Citizenship", "likely"),
    _t("CBLZ", "aml_case", "Banka kodları", "Bankleitzahl", "likely"),
    _t("CRECHTF", "aml_case", "Hukuki şekil", "Rechtsform", "likely"),
    _t("CBERUFTYP", "aml_case", "Meslek tipleri", "Berufstyp", "likely"),
    _t("CVORFALL", "aml_case", "Vakalar / olaylar", "Vorfall", "likely"),
    _t("CVORTAT", "aml_case", "Öncül suçlar", "Vortat", "likely"),
    _t("CVFAAUFF", "aml_case", "Şüpheli vaka bulguları", "Verdachtsfall-Auffälligkeit", "guess"),
    _t("CANZEIGE", "aml_case", "Şüpheli işlem bildirimleri", "Anzeige", "likely"),
    _t("CANZKUND", "aml_case", "Bildirimdeki müşteriler", "Anzeige-Kunde", "likely"),
    _t("CANZKONT", "aml_case", "Bildirimdeki hesaplar", "Anzeige-Konto", "likely"),
    _t("CANZTRAN", "aml_case", "Bildirimdeki işlemler", "Anzeige-Transaktion", "likely"),
    _t("CBRIEF", "aml_case", "Mektuplar", "Brief", "likely"),
    _t("CSBRIEF", "aml_case", "Seri mektuplar", "Serienbrief", "likely"),
    _t("CTXTBAU", "aml_case", "Metin şablonları", "Textbaustein", "likely"),
    _t("CDRKFORM", "aml_case", "Baskı formları", "Druckformular", "likely"),
    # screening lists, KYC results, embargo
    _t("SL_MAIN", "lists", "Liste ana kaydı", "", "likely"),
    _t("SL_NAMES", "lists", "Liste kişi/kurum adları", "", "likely"),
    _t("SL_ADDR", "lists", "Liste adresleri", "", "likely"),
    _t("SL_BIRTH", "lists", "Doğum bilgileri", "", "likely"),
    _t("SL_PASS", "lists", "Pasaport bilgileri", "", "likely"),
    _t("SL_CITIZ", "lists", "Uyruk bilgileri", "", "likely"),
    _t("SL_RELATIONS", "lists", "Liste kayıtları arası ilişkiler", "", "likely"),
    _t("SL_LISTINFO", "lists", "Liste bilgileri", "", "likely"),
    _t("SL_WLDATE", "lists", "İzleme listesi sürüm tarihi", "Watch-list date", "likely"),
    _t("PRESULT_ARCHIVE", "kyc_result", "PRESULT arşivi", "", "likely"),
    _t("PRESULT1706", "kyc_result", "PRESULT'un sürüm geçişinde alınmış kopyası (büyük olasılıkla Haziran 2017)", "", "likely",
       "Taşımaya dahil edilmesi beklenmez; yedek tablo."),
    _t("PHIT", "kyc_result", "Tarama isabetleri", "Hit", "likely"),
    _t("PSLSET", "kyc_result", "Tarama listesi setleri", "Screening List Set", "likely"),
    _t("PEPPARAM", "kyc_result", "PEP tarama parametreleri", "", "likely"),
    _t("PERSSTAT", "kyc_result", "Kişi durumu", "Personenstatus", "likely"),
    _t("EDECTAB", "embargo", "Embargo karar tablosu", "Decision table", "likely"),
    _t("EWLDATE", "embargo", "Embargo liste tarihi", "Watch-list date", "likely"),
    _t("EPAYSYSR", "embargo", "Ödeme sistemi kuralları", "Payment system rule", "likely"),
    _t("ESW", "embargo", "Stop-word listesi", "Stop words", "likely"),
    _t("EMBINST", "embargo", "Embargo kurum ayarları", "Institut", "guess"),
    _t("EMBLOCK", "embargo", "Embargo kilitleri", "Lock", "guess"),
    _t("EMBDWHPE_DATA", "embargo", "Çözülmemiş", "", "unresolved"),
    # platform
    _t("TBDEF", "platform", "Tanımlar (uygulama sözlüğü adayı)", "Definition", "guess"),
    _t("TBBO", "platform", "İş nesneleri (uygulama sözlüğü adayı)", "Business Object", "guess"),
    _t("TBFELDZ", "platform", "Alan atama/eşleme (uygulama sözlüğü adayı)", "Feldzuordnung", "guess"),
    _t("TBINFO", "platform", "Açıklama metinleri", "Info", "guess"),
    _t("TBDOMAIN", "platform", "Kod listeleri (domain)", "Domäne", "guess"),
    _t("TBDOMVAL", "platform", "Kod listesi değerleri", "Domänenwert", "guess"),
    _t("TBDOMHST", "platform", "Kod listesi tarihçesi", "Domänen-Historie", "guess"),
    _t("TBMUSS", "platform", "Zorunlu alanlar", "Mussfelder", "guess"),
    _t("TBLNG", "platform", "Dil kaynakları / arayüz metinleri", "Language", "guess"),
    _t("TBRESSOURCE", "platform", "Arayüz metin kaynakları", "Ressource", "guess"),
    _t("TBPARA", "platform", "Platform parametreleri", "Parameter", "likely"),
    _t("TBAPPCONFIG", "platform", "Uygulama konfigürasyonu", "", "likely"),
    _t("TBFILIAL", "platform", "Şubeler", "Filiale", "likely"),
    _t("TBDATRECHT", "platform", "Veri erişim yetkileri", "Datenrecht", "likely"),
    _t("TBPATCH", "platform", "Uygulanan yama geçmişi: kurulu sürümün kesin kaynağı", "Patch", "likely",
       "Vendor'dan belge isterken sürüm numarası buradan okunur."),
    _t("TBLOGIN", "platform", "Giriş kayıtları", "Login", "likely"),
    _t("TBLOGINH", "platform", "Giriş kayıtları tarihçesi", "Login-Historie", "likely"),
    _t("TBAUDIT", "platform", "Platform denetim kayıtları", "Audit", "likely"),
    _t("TBREPORT", "platform", "Rapor tanımları", "Report", "likely"),
    _t("TBSYNC", "platform", "Senkronizasyon", "Sync", "guess"),
    # local MASAK bridge
    _t("MASAK_2_SIRON_FIELD_MAP", "masak", "MASAK ŞİB form alanlarının Siron sütunlarına eşlemesi", "", "likely",
       "\"Hangi Siron sütunu hangi iş kavramına karşılık gelir\" bilgisini ŞİB alanları için zaten içerir; "
       "tersine mühendislikte kaldıraç."),
    _t("BANK_2_MASAK_CODE", "masak", "Banka iç kodlarının (işlem türü, meslek, ülke, hukuki şekil) MASAK kodlarına çevirisi", "", "likely"),
    _t("PARAM_MESLEK", "masak", "Yerel meslek kod parametreleri (Siron'da CBERUFTYP karşılığı)", "", "likely"),
    _t("PARAM_ULKEKODU", "masak", "Yerel ülke kod parametreleri (Siron'da GWGLAND karşılığı)", "", "likely"),
    _t("SIBFORM", "masak", "Şüpheli İşlem Bildirimi formu (hipotez)", "SİB Form?", "guess",
       "Doğrulama: SELECT * FROM SIBFORM WHERE ROWNUM <= 20 ve sütunlarda SK-xx, VKN/TCKN, işlem türü izi."),
    _t("LOCKEDSIBFORMS", "masak", "Kilitli bildirim formları (hipotez)", "", "guess"),
    _t("MMNACHR", "unknown", "Mesajlar (olası)", "Nachricht", "unresolved"),
    _t("MMNACHRZ", "unknown", "Mesaj ekleri? (olası)", "Nachricht-Zusatz", "unresolved"),
    _t("WSSTATUS", "unknown", "Web servis durumu?", "", "guess"),
    _t("WSLOCK", "unknown", "Web servis kilidi?", "", "guess"),
]
KNOWN_BY_NAME: Dict[str, KnownTable] = {t.name: t for t in KNOWN_TABLES}


# --------------------------------------------------------------------------- columns and terms

# Column names seen in real Siron SQL (verified).
KNOWN_COLUMNS: Dict[str, str] = {
    "INSTITUTSNR": "Kurum (enstitü) numarası; şema A<no> ile eşleşir (ör. A0001)",
    "KUNDNR": "Müşteri numarası",
    "HISTBIS": "Geçerlilik bitişi; '9999' = güncel kayıt",
    "HISTVON": "Geçerlilik başlangıcı",
    "KYC_VORNAME": "Ad",
    "KYC_NACHNAME": "Soyad",
    "RISIKO": "Risk sınıfı",
    "ERFASSER": "Kaydı giren kullanıcı",
    "RL_KUERZEL": "Referans listesi kodu (hangi kod listesi)",
    "BEZ": "Kod değeri (Bezeichnung)",
    "KOMMENTAR": "Kod açıklaması",
}
KYC_SP = re.compile(r"^KYC_SP_(\d{2})$")

# German fragments found in Siron table/column names -> Turkish meaning. Longest match first.
TERMS: List[Tuple[str, str, str]] = [
    ("GELDWAESCHE", "kara para aklama", "Geldwäsche"),
    ("HANDANW", "işlem talimatı", "Handlungsanweisung"),
    ("VERDACHT", "şüphe / şüpheli", "Verdacht"),
    ("INSTITUT", "kurum", "Institut"),
    ("TREFFER", "isabet / alarm", "Treffer"),
    ("TRANSAKT", "işlem", "Transaktion"),
    ("NACHNAME", "soyad", "Nachname"),
    ("VORNAME", "ad", "Vorname"),
    ("KUNDENNR", "müşteri numarası", "Kundennummer"),
    ("KONTONR", "hesap numarası", "Kontonummer"),
    ("ERFASSER", "kaydı giren", "Erfasser"),
    ("KOMMENTAR", "açıklama", "Kommentar"),
    ("KATEGORIE", "kategori", "Kategorie"),
    ("RECHTSFORM", "hukuki şekil", "Rechtsform"),
    ("RECHTF", "hukuki şekil", "Rechtsform"),
    ("AUSWEIS", "kimlik belgesi", "Ausweis"),
    ("AUSW", "kimlik belgesi", "Ausweis"),
    ("BERUF", "meslek", "Beruf"),
    ("VORFALL", "vaka / olay", "Vorfall"),
    ("VORTAT", "öncül suç", "Vortat"),
    ("ANZEIGE", "bildirim (ŞİB)", "Anzeige"),
    ("BRIEF", "mektup", "Brief"),
    ("TXTBAU", "metin şablonu", "Textbaustein"),
    ("DRKFORM", "baskı formu", "Druckformular"),
    ("FILIALE", "şube", "Filiale"),
    ("FILIAL", "şube", "Filiale"),
    ("RISIKO", "risk", "Risiko"),
    ("RIKLAS", "risk sınıfı", "Risikoklasse"),
    ("KLASSE", "sınıf", "Klasse"),
    ("WAEHR", "para birimi", "Währung"),
    ("BETRAG", "tutar", "Betrag"),
    ("BUCHUNG", "kayıt / muhasebe", "Buchung"),
    ("BUCH", "kayıt / muhasebe", "Buchung"),
    ("VALUTA", "valör tarihi", "Valuta"),
    ("DATUM", "tarih", "Datum"),
    ("ZEIT", "zaman / dönem", "Zeit"),
    ("ANSCHRIFT", "adres", "Anschrift"),
    ("STRASSE", "sokak", "Straße"),
    ("ORT", "şehir / yer", "Ort"),
    ("PLZ", "posta kodu", "Postleitzahl"),
    ("GEBURT", "doğum", "Geburt"),
    ("NATION", "uyruk", "Nationalität"),
    ("STAAT", "devlet / uyruk", "Staat"),
    ("LAND", "ülke", "Land"),
    ("KUNDE", "müşteri", "Kunde"),
    ("KUND", "müşteri", "Kunde"),
    ("KONTO", "hesap", "Konto"),
    ("KONT", "hesap", "Konto"),
    ("TRANS", "işlem", "Transaktion"),
    ("BENUT", "kullanıcı", "Benutzer"),
    ("ROLLE", "rol", "Rolle"),
    ("INDIZ", "gösterge (tespit kuralı)", "Indiz"),
    ("INKL", "dahil listesi", "Inklusion"),
    ("EXKL", "hariç listesi", "Exklusion"),
    ("FELD", "alan", "Feld"),
    ("TEXT", "metin", "Text"),
    ("KUERZEL", "kısaltma / kod", "Kürzel"),
    ("BEZ", "tanım / ad", "Bezeichnung"),
    ("NAME", "ad", "Name"),
    ("SCHLUESSEL", "anahtar", "Schlüssel"),
    ("WERT", "değer", "Wert"),
    ("PARA", "parametre", "Parameter"),
    ("STAT", "durum / istatistik", "Status / Statistik"),
    ("HIST", "tarihçe", "Historie"),
    ("BIS", "bitiş (... e kadar)", "bis"),
    ("VON", "başlangıç (... den)", "von"),
    ("ANZ", "sayı / bildirim", "Anzahl / Anzeige"),
    ("NR", "numara", "Nummer"),
    ("KZ", "işaret / bayrak", "Kennzeichen"),
    ("JN", "evet/hayır bayrağı", "Ja/Nein"),
    ("BLZ", "banka kodu", "Bankleitzahl"),
    ("SYNONYM", "ad varyantı", "Synonym"),
    ("HIT", "isabet", "hit"),
    ("SCORE", "puan", "score"),
    ("SCOR", "puan", "score"),
]
_TERMS_SORTED = sorted(TERMS, key=lambda t: -len(t[0]))
_SUFFIXES = {"NR", "KZ", "JN", "BIS", "VON"}


def explain(name: str) -> List[Tuple[str, str, str]]:
    """German fragments in a table/column name with their meaning, left to right.

    Greedy longest match; only a hint for German-named Siron columns.
    """
    up = (name or "").upper()
    if up in KNOWN_COLUMNS:
        return [(up, KNOWN_COLUMNS[up], "doğrulanmış")]
    m = KYC_SP.match(up)
    if m:
        return [(up, "KYC serbest alanı %s: anlamı kuruma göre değişir (TBRLEINT ile çözülür)" % m.group(1), "doğrulanmış")]
    found, i = [], 0
    while i < len(up):
        for frag, meaning, de in _TERMS_SORTED:
            if up.startswith(frag, i):
                # short fragments only count at a word start (or as a suffix) to avoid false hits
                at_end = i + len(frag) == len(up)
                if len(frag) <= 3 and i and up[i - 1] != "_" and not (frag in _SUFFIXES and at_end):
                    continue
                found.append((frag, meaning, de))
                i += len(frag)
                break
        else:
            i += 1
    return found


def explain_text(name: str) -> str:
    parts = explain(name)
    if len(parts) == 1 and parts[0][0] == (name or "").upper():
        return parts[0][1]
    return " · ".join("%s = %s" % (frag, meaning) for frag, meaning, _ in parts)


# --------------------------------------------------------------------------- classification

@dataclass
class Classification:
    module: Module
    family: Optional[Family]
    known: Optional[KnownTable]

    @property
    def confidence(self) -> str:
        if self.known:
            return self.known.confidence
        return self.family.confidence if self.family else "unresolved"

    @property
    def basis(self) -> str:
        return "Bilinen tablo" if self.known else "Önek eşleşmesi"

    @property
    def meaning(self) -> str:
        if self.known:
            return self.known.meaning
        return self.family.meaning if self.family else ""


def classify(table_name: str) -> Optional[Classification]:
    name = (table_name or "").upper()
    known = KNOWN_BY_NAME.get(name)
    family = next((f for f in FAMILIES if f.regex.search(name)), None)
    if known:
        return Classification(MODULE_BY_ID[known.module], family, known)
    if family:
        return Classification(MODULE_BY_ID[family.module], family, None)
    return None


# --------------------------------------------------------------------------- verification queries

@dataclass
class Query:
    id: str
    category: str
    title: str
    purpose: str
    sql: str
    runnable: bool = True          # SELECT/WITH the app can run read-only
    needs: str = ""
    app: str = ""                  # endpoint of the page that already does this

    def for_schema(self, schema: str) -> str:
        return self.sql.replace("{schema}", schema or "SIRON")


QUERY_CATEGORIES = ["Araştırma bulgularını doğrula", "Uygulama sözlüğü adayları", "Şema envanteri",
                    "Anahtarlar ve ilişkiler", "Kullanım ve gerçek SQL", "Kod listeleri ve konfigürasyon", "MASAK köprüsü"]

QUERIES: List[Query] = [
    Query("verify-owner", "Araştırma bulgularını doğrula", "Doğrulanmış tablolar hangi şemada?",
          "KYCCUST, PRESULT, TBRLEINT, TBRLIST hangi şemada duruyor? Örnek kurulumda kurum verisi A<no> şemasında, "
          "referans verisi GLOBAL'de.",
          "SELECT owner, table_name FROM all_tables\nWHERE table_name IN ('KYCCUST','PRESULT','TBRLEINT','TBRLIST')\nORDER BY owner, table_name"),
    Query("verify-columns", "Araştırma bulgularını doğrula", "Doğrulanmış tabloların sütunları",
          "Araştırmadaki sütun adlarının (KUNDNR, HISTBIS, RL_KUERZEL, BEZ, KOMMENTAR...) sizde de olup olmadığını gösterir.",
          "SELECT owner, table_name, column_name, data_type, data_length FROM all_tab_columns\n"
          "WHERE table_name IN ('KYCCUST','PRESULT','TBRLEINT','TBRLIST','TBRLISTFIELD','TBRLEINTFIELD')\n"
          "ORDER BY owner, table_name, column_id"),
    Query("code-lists", "Araştırma bulgularını doğrula", "Kod listesi sözlüğü (TBRLEINT)",
          "Hangi liste (RL_KUERZEL) kaç kod tutuyor, örnek kod ve açıklama. Ekrandaki kodların anlamı buradan gelir.",
          "SELECT rl_kuerzel, COUNT(*) AS kod_sayisi, MIN(bez) AS ornek_kod, MIN(kommentar) AS ornek_aciklama\n"
          "FROM tbrleint WHERE histbis = '9999'\nGROUP BY rl_kuerzel ORDER BY rl_kuerzel",
          needs="TBRLEINT başka şemadaysa (ör. GLOBAL) önüne şema adını yazın."),
    Query("historised", "Araştırma bulgularını doğrula", "Tarihçeli tablolar (HISTBIS)",
          "HISTBIS sütunu taşıyan tablolar tarihçeli ana veridir; taşımada genellikle HISTBIS = '9999' filtresi gerekir.",
          "SELECT table_name FROM all_tab_columns\nWHERE owner = '{schema}' AND column_name = 'HISTBIS'\nORDER BY table_name"),
    Query("comments", "Uygulama sözlüğü adayları", "Oracle kataloğunda vendor yorumu var mı?",
          "Siron'un 3 DBMS'de çalışan 4GL mirası nedeniyle büyük olasılıkla boş çıkar; bu beklenen bir durumdur.",
          "SELECT SUM(CASE WHEN comments IS NOT NULL THEN 1 ELSE 0 END) AS yorumlu_tablo, COUNT(*) AS toplam_tablo\n"
          "FROM all_tab_comments WHERE owner = '{schema}' AND table_type = 'TABLE'"),
    Query("dict-candidates", "Uygulama sözlüğü adayları", "Uygulama sözlüğü adaylarının sütunları",
          "TBDEF, TBBO, TBFELDZ, TBDOMAIN... gerçekten tablo/alan tanımı tutuyor mu?",
          "SELECT c.table_name, c.column_id, c.column_name, c.data_type, c.data_length, t.num_rows\n"
          "FROM all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name\n"
          "WHERE c.owner = '{schema}'\n"
          "  AND c.table_name IN ('TBDEF','TBBO','TBFELDZ','TBINFO','TBDOMAIN','TBDOMVAL','TBDOMHST','TBMUSS',\n"
          "                       'TBLNG','TBRESSOURCE','TBAPPCONFIG','TBPARA','GWGFELD','GWGFTEXT','GWGPARA','TDIREPOS')\n"
          "ORDER BY c.table_name, c.column_id"),
    Query("label-tables", "Uygulama sözlüğü adayları", "Etiket / kod listesi / sözlük yapısındaki tablolar",
          "Dil, metin, etiket, alan, domain sütunlarından en az ikisini taşıyan tablolar: GUI etiketlerinin kaynağı adayları.",
          "SELECT c.table_name, LISTAGG(c.column_name, ', ') WITHIN GROUP (ORDER BY c.column_id) AS cols, t.num_rows\n"
          "FROM all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name\n"
          "WHERE c.owner = '{schema}'\n"
          "  AND REGEXP_LIKE(c.column_name, '(LANG|LNG|SPRACHE|TEXT|TXT|LABEL|DESCR|BESCHR|BEZ|CAPTION|TABNAME|TABLE_NAME|TABELLE|COLNAME|FELD|FIELD|DOMAIN|DOMVAL|CODE)')\n"
          "GROUP BY c.table_name, t.num_rows HAVING COUNT(*) >= 2\nORDER BY t.num_rows DESC NULLS LAST"),
    Query("table-name-cols", "Uygulama sözlüğü adayları", "Tablo/nesne adı tutan sütunlar",
          "Başka tabloların adını veri olarak saklayabilecek sütunlar.",
          "SELECT DISTINCT table_name, column_name FROM all_tab_columns\nWHERE owner = '{schema}'\n"
          "  AND REGEXP_LIKE(column_name, '(TAB(LE|ELLE)?_?NAME|TABNAME|ENTITY|OBJEKT|OBJECT_NAME)')\nORDER BY 1, 2"),
    Query("dict-scan", "Uygulama sözlüğü adayları", "Hangi tablo başka tabloların ADINI veri olarak saklıyor?",
          "Küçük tabloların metin sütunlarını tarar (PL/SQL). Pozitif çıkan tablo uygulamanın kendi veri sözlüğüdür. "
          "Uygulama yalnız SELECT çalıştırdığı için SQL*Plus / SQL Developer'da çalıştırın.",
          "SET SERVEROUTPUT ON SIZE UNLIMITED\nDECLARE\n  v_cnt NUMBER;\nBEGIN\n"
          "  FOR c IN (SELECT c.table_name, c.column_name\n"
          "            FROM all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name\n"
          "            WHERE c.owner = '{schema}' AND c.data_type IN ('VARCHAR2','CHAR','NVARCHAR2')\n"
          "              AND c.data_length >= 6 AND NVL(t.num_rows, 1) < 200000)\n  LOOP\n"
          "    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM {schema}.\"' || c.table_name || '\" WHERE UPPER(\"' || c.column_name ||\n"
          "                      '\") IN (''GWGKUNDE'',''GWGKONTO'',''GWGTRANS'',''CKUNDE'',''GWATRHIT'',''KSLMAIN'')' INTO v_cnt;\n"
          "    IF v_cnt > 0 THEN\n      DBMS_OUTPUT.PUT_LINE(c.table_name || '.' || c.column_name || ' -> ' || v_cnt);\n"
          "    END IF;\n  END LOOP;\nEND;\n/", runnable=False),
    Query("prefix-count", "Şema envanteri", "Önek başına tablo sayısı",
          "GWG, GWA, C, SL_, KSL, EMB, TB, TBQ, FAR, TAX, CASE, GB_, RB_, TDI... ailelerinin büyüklüğü.",
          "SELECT REGEXP_SUBSTR(table_name, '^[A-Z]+_?') AS prefix, COUNT(*) AS tables\n"
          "FROM all_tables WHERE owner = '{schema}'\nGROUP BY REGEXP_SUBSTR(table_name, '^[A-Z]+_?')\nORDER BY tables DESC",
          app="research"),
    Query("inventory", "Şema envanteri", "Tablo envanteri: istatistik, son DML, oluşturma zamanı",
          "INSERTS ≫ UPDATES işlem/log/alarm tablosu; az satırlı ve çok referans alan tablolar kod listesi.",
          "SELECT t.table_name, REGEXP_SUBSTR(t.table_name, '^[A-Z]+_?') AS prefix, tc.comments AS table_comment,\n"
          "       t.num_rows, t.last_analyzed, m.inserts, m.updates, m.deletes, m.timestamp AS last_dml,\n"
          "       o.created, o.last_ddl_time\nFROM all_tables t\n"
          "LEFT JOIN all_tab_comments tc ON tc.owner = t.owner AND tc.table_name = t.table_name\n"
          "LEFT JOIN all_tab_modifications m ON m.table_owner = t.owner AND m.table_name = t.table_name AND m.partition_name IS NULL\n"
          "LEFT JOIN all_objects o ON o.owner = t.owner AND o.object_name = t.table_name AND o.object_type = 'TABLE'\n"
          "WHERE t.owner = '{schema}'\nORDER BY prefix, t.table_name",
          needs="Güncel DML sayaçları için önce DBMS_STATS.FLUSH_DATABASE_MONITORING_INFO (DBA)."),
    Query("object-types", "Şema envanteri", "Şemadaki nesne türleri", "Tablo, view, paket, tetikleyici sayıları.",
          "SELECT object_type, COUNT(*) AS cnt FROM all_objects WHERE owner = '{schema}'\nGROUP BY object_type ORDER BY cnt DESC"),
    Query("hubs", "Anahtarlar ve ilişkiler", "En çok referans alan \"hub\" tablolar",
          "En çok FK ile referans alınan tablo genellikle müşteri/taraf tablosudur.",
          "SELECT pk.table_name AS parent_table, COUNT(*) AS referencing_fks\nFROM all_constraints fk\n"
          "JOIN all_constraints pk ON pk.owner = fk.r_owner AND pk.constraint_name = fk.r_constraint_name\n"
          "WHERE fk.owner = '{schema}' AND fk.constraint_type = 'R'\nGROUP BY pk.table_name ORDER BY referencing_fks DESC",
          app="relations"),
    Query("checks", "Anahtarlar ve ilişkiler", "Check kısıtları: izin verilen kod kümeleri",
          "Kolonların alabileceği değerler çoğu zaman burada yazılıdır.",
          "SELECT table_name, constraint_name, search_condition_vc\nFROM all_constraints\n"
          "WHERE owner = '{schema}' AND constraint_type = 'C' AND generated = 'USER NAME'\nORDER BY table_name"),
    Query("shared-cols", "Anahtarlar ve ilişkiler", "FK yoksa: paylaşılan sütun adları",
          "Java/Hibernate çağı uygulamalarda FK tanımlanmaz; ortak ID/NR/KEY/CODE sütunları ilişki ipucudur.",
          "SELECT a.table_name, a.column_name, COUNT(*) OVER (PARTITION BY a.column_name) AS tables_sharing_col\n"
          "FROM all_tab_columns a\nWHERE a.owner = '{schema}'\n"
          "  AND a.column_name IN (SELECT column_name FROM all_tab_columns WHERE owner = '{schema}' GROUP BY column_name HAVING COUNT(*) > 1)\n"
          "  AND (a.column_name LIKE '%ID' OR a.column_name LIKE '%NR' OR a.column_name LIKE '%KEY%' OR a.column_name LIKE '%NO' OR a.column_name LIKE '%CODE')\n"
          "ORDER BY tables_sharing_col DESC, a.column_name, a.table_name", app="relations"),
    Query("indexes", "Anahtarlar ve ilişkiler", "İndeksler: uygulama hangi sütunlardan arıyor",
          "Ekran aramalarının hangi kolonlardan yapıldığına dair ipucu.",
          "SELECT i.table_name, i.index_name, i.uniqueness,\n"
          "       LISTAGG(ic.column_name, ', ') WITHIN GROUP (ORDER BY ic.column_position) AS idx_cols\n"
          "FROM all_indexes i JOIN all_ind_columns ic ON ic.index_owner = i.owner AND ic.index_name = i.index_name\n"
          "WHERE i.table_owner = '{schema}'\nGROUP BY i.table_name, i.index_name, i.uniqueness ORDER BY i.table_name"),
    Query("sessions", "Kullanım ve gerçek SQL", "Siron şemasına kim bağlanıyor?",
          "Kullanıcılar ve batch aktifken: uygulama MODULE/ACTION etiketliyor mu, hangi DB hesapları var? "
          "Yakalama formunda seçeceğiniz kullanıcılar bunlardır.",
          "SELECT username, osuser, machine, program, module, action, service_name, COUNT(*) AS sessions\n"
          "FROM v$session WHERE username IS NOT NULL\n"
          "GROUP BY username, osuser, machine, program, module, action, service_name\nORDER BY sessions DESC",
          needs="V$SESSION okuma yetkisi"),
    Query("pool-usage", "Kullanım ve gerçek SQL", "Paylaşılan havuz: her tabloya dokunan SQL",
          "Hangi tablo hangi modülden kaç kez okunmuş; audit açılmadan önce hızlı ön keşif.",
          "SELECT p.object_name AS table_name, s.module, s.parsing_schema_name,\n"
          "       SUM(s.executions) AS execs, MAX(s.last_active_time) AS last_seen, COUNT(DISTINCT s.sql_id) AS distinct_sql\n"
          "FROM v$sql s JOIN v$sql_plan p ON p.sql_id = s.sql_id AND p.child_number = s.child_number\n"
          "WHERE p.object_owner = '{schema}' AND p.object_type LIKE 'TABLE%'\n"
          "GROUP BY p.object_name, s.module, s.parsing_schema_name\nORDER BY table_name, execs DESC",
          needs="V$SQL / V$SQL_PLAN okuma yetkisi"),
    Query("grants", "Kullanım ve gerçek SQL", "Hangi DB hesabı hangi tabloda yetkili?",
          "Modül şemaları, batch ve rapor kullanıcıları ayrışır; yakalama için ek kullanıcıları gösterir.",
          "SELECT grantee, table_name, LISTAGG(privilege, ',') WITHIN GROUP (ORDER BY privilege) AS privs\n"
          "FROM all_tab_privs WHERE table_schema = '{schema}'\nGROUP BY grantee, table_name ORDER BY grantee, table_name"),
    Query("plsql-writes", "Kullanım ve gerçek SQL", "Tablolara YAZAN PL/SQL satırları",
          "Paket kaynak kodunda INSERT/UPDATE/DELETE/MERGE geçen satırlar.",
          "SELECT s.type, s.name, s.line, TRIM(s.text) AS src\nFROM all_source s\nWHERE s.owner = '{schema}'\n"
          "  AND REGEXP_LIKE(s.text, '(INSERT\\s+INTO|UPDATE|DELETE\\s+FROM|MERGE\\s+INTO)\\s+(\"?{schema}\"?\\.)?\"?(GWG|GWA|C|TB)[A-Z0-9_]*', 'i')\n"
          "ORDER BY s.name, s.line"),
    Query("triggers", "Kullanım ve gerçek SQL", "Tetikleyiciler",
          "Audit/tarihçe/denormalizasyon mantığı tablonun anlamını açık eder.",
          "SELECT table_name, trigger_name, trigger_type, triggering_event, status\n"
          "FROM all_triggers WHERE table_owner = '{schema}'\nORDER BY table_name, trigger_name"),
    Query("seg-stat", "Kullanım ve gerçek SQL", "Lisanssız segment aktivitesi",
          "Okuma ağırlıklı (referans/kod) ve yazma ağırlıklı (işlem/alarm/log) tabloları ayırır. "
          "DBA_HIST_SEG_STAT ve _OBJ Diagnostics Pack'e dahil değildir.",
          "SELECT o.object_name, o.object_type, SUM(s.logical_reads_delta) AS reads,\n"
          "       SUM(s.db_block_changes_delta) AS block_changes, SUM(s.table_scans_delta) AS full_scans\n"
          "FROM dba_hist_seg_stat s\n"
          "JOIN dba_hist_seg_stat_obj o ON o.dbid = s.dbid AND o.ts# = s.ts# AND o.obj# = s.obj# AND o.dataobj# = s.dataobj#\n"
          "WHERE o.owner = '{schema}'\nGROUP BY o.object_name, o.object_type ORDER BY block_changes DESC",
          needs="DBA yetkisi"),
    Query("awr", "Kullanım ve gerçek SQL", "AWR tarihçesi: haftalar boyunca tablo × modül",
          "Yalnız Diagnostics Pack lisansı varsa çalıştırın; lisanssız EE'de bir önceki sorguyu kullanın.",
          "SELECT hp.object_name, hs.module, SUM(hs.executions_delta) AS execs, COUNT(DISTINCT hs.sql_id) AS stmts\n"
          "FROM dba_hist_sqlstat hs\n"
          "JOIN dba_hist_sql_plan hp ON hp.sql_id = hs.sql_id AND hp.plan_hash_value = hs.plan_hash_value AND hp.dbid = hs.dbid\n"
          "WHERE hp.object_owner = '{schema}' AND hp.object_type LIKE 'TABLE%'\n"
          "GROUP BY hp.object_name, hs.module ORDER BY hp.object_name, execs DESC",
          needs="Oracle Diagnostics Pack LİSANSI"),
    Query("config-tables", "Kod listeleri ve konfigürasyon", "KEY/VALUE ya da PARAM/WERT çiftli konfigürasyon tabloları",
          "Küçük konfigürasyon tabloları modül sınırlarını gösterir.",
          "SELECT c.table_name, t.num_rows\nFROM all_tab_columns c JOIN all_tables t ON t.owner = c.owner AND t.table_name = c.table_name\n"
          "WHERE c.owner = '{schema}' AND REGEXP_LIKE(c.column_name, '(PARAM|PARA|KEY|SCHLUESSEL|WERT|VALUE|CONFIG|SETTING)')\n"
          "GROUP BY c.table_name, t.num_rows HAVING COUNT(*) >= 2\nORDER BY t.num_rows"),
    Query("version", "Kod listeleri ve konfigürasyon", "Kurulu sürüm (TBPATCH)",
          "Vendor'dan belge isterken kurulu sürümü bildirmek gerekir; yama geçmişi tablosu bunu kesin verir.",
          "SELECT * FROM {schema}.tbpatch WHERE ROWNUM <= 200"),
    Query("masak-map", "MASAK köprüsü", "MASAK_2_SIRON_FIELD_MAP içeriği",
          "ŞİB form alanlarının hangi Siron sütunlarına eşlendiğini gösterir: bankanın elindeki hazır sütun-kavram eşlemesi.",
          "SELECT * FROM {schema}.masak_2_siron_field_map"),
    Query("sibform", "MASAK köprüsü", "SIBFORM örneği",
          "Sütunlarda SK-xx şüphe kodu, VKN/TCKN, işlem türü gibi MASAK alanları varsa \"Şüpheli İşlem Bildirimi\" okuması doğrulanır.",
          "SELECT * FROM {schema}.sibform WHERE ROWNUM <= 20"),
]
QUERY_BY_ID = {q.id: q for q in QUERIES}


# --------------------------------------------------------------------------- channels and key findings

CHANNELS = [
    {"name": "IMTF Customer Portal", "role": "Tek resmi kanal: ürün dokümantasyonu yalnız destek portalından verilir.",
     "contact": "imtf.atlassian.net/servicedesk · support@imtf.com", "url": "https://imtf.com/customer-support/"},
    {"name": "IMTF Siron GmbH (Bensheim, Almanya)", "role": "Siron şemasını yazan eski Tonbeller mühendislik ekibi; veri modeli sorusu için en doğru adres.",
     "contact": "Destek +49 6251 8262697 · Merkez +49 6251 8262790 · Stubenwald-Allee 19, 64625 Bensheim",
     "url": "https://imtf.com/about-us/contact/"},
    {"name": "Holicy Consulting (İstanbul)", "role": "IMTF'nin Türkiye için listelediği tek teslimat ortağı; rolü (satış/uygulama/destek) belirsiz.",
     "contact": "Büyükdere Cad. FERKO Signature No. 175/2, Şişli", "url": "https://imtf.com/imtf-partners/"},
    {"name": "İlk uygulayıcı (banka arşivi)", "role": "İlk Tonbeller/FICO kurulumunu yapan firma; eşleme tabloları ve arayüz spesifikasyonu muhtemelen bankanın içinde.",
     "contact": "Bankanın tedarik / proje arşivi", "url": ""},
    {"name": "IMTF Campus", "role": "Ücretli abonelikte teknik kurslar ve indirilebilir belgeler; ücretsiz katmanda CRS/FATCA webinarı.",
     "contact": "campus.imtf.com", "url": "https://campus.imtf.com/additional-info"},
]

DOC_REQUESTS = [
    "Kurulu sürüm için veri modeli: tablo ve sütun açıklamaları (Datenbankbeschreibung)",
    "İçe aktarım arayüz tanımı: Kunde/Konto/Transaktion/Relation/Adresse kayıt yerleşimleri (Schnittstellenbeschreibung)",
    "Kurulum ve yönetim kılavuzları, sürüm notları",
    "Siron GUI'den ekran → alan → sütun tanımı dışa aktarma yolu (varsa)",
    "Sürüm numarasını TBPATCH tablosundan okuyup talebe ekleyin; başlık tahmin etmek yerine içeriği tanımlayın",
]

KEY_FINDINGS = [
    ("verified", "Açık web'de hazır bir \"tablolar tablosu\" yok",
     "~40 ayırt edici tablo adı açık web'de ve GitHub kod aramasında geçmedi; Siron DDL'i kamuya sızmamış."),
    ("verified", "KYCCUST, PRESULT ve TBRLEINT gerçek Siron SQL'inde görüldü",
     "Bir T24 ↔ Siron KYC entegrasyonunun kodunda: KYC müşteri tablosu, KYC risk sonucu ve kod listesi girdileri."),
    ("verified", "Kodların anlamını veren tablo: TBRLEINT",
     "RL_KUERZEL liste kodu, BEZ kod, KOMMENTAR açıklama, HISTBIS='9999' güncel kayıt. Başlıklar TBRLIST'te."),
    ("verified", "HISTBIS = '9999' güncel kayıt kalıbı",
     "Siron tablolarının çoğu tarihçeli; taşımada güncel kaydı seçmek için bu filtre gerekir."),
    ("verified", "Şema düzeni: kurum şeması + GLOBAL",
     "Örnek kurulumda kurum verisi A0001 şemasında, ortak referans verisi GLOBAL'de. Kendi kurulumunuzda kontrol edin."),
    ("likely", "Önekler modül düzeyinde okunabiliyor",
     "GWG = AML (GwG), TB = Tonbeller platformu, SL_/KSL = listeler, E/EMB = Embargo, FAR/TAX = FATCA/CRS, CASE/WORKFLOW = ACM."),
    ("guess", "Tablo düzeyindeki anlamların çoğu hipotez",
     "Tek tek tablo adları kamuya açık belgede görülmediği için doğrulanmış sayılmaz; yakalamalar ve veri ile teyit edilmeli."),
    ("likely", "PARAM_*, MASAK_2_SIRON_FIELD_MAP, BANK_2_MASAK_CODE vendor şeması değil",
     "Bankanın MASAK ŞİB kod listelerine kurduğu köprü; vendor belgesi beklenmemeli, bilgisi uyum biriminde."),
    ("likely", "Resmi belge yalnız IMTF portalından",
     "IMTF ürün dokümantasyonunu yalnız destek portalı üzerinden veriyor; Bensheim ekibi veri modeli için doğru adres."),
]
