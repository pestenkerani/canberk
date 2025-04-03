import random

# Kişilere özel yanıt sözlükleri
SPECIAL_REPLIES = {
    "Kutay": [
        "Naber mühendiscan... hala geceleri devre mi çiziyon yoksa rüyanda takas veto mu yapıyorsun knk?",
        "Mühendiscan, takas sistemine algoritma yazdın mı yoksa hâlâ Excel’le mi çalışıyorsun mk?",
        "Sen naber diyorsun ama ben hala senin veto mantığını debug edemedim mühendiscan.",
        "Naber mühendiscan. Veto sistemi üzerine yüksek lisans mı yapıyorsun hala?"
    ],
    "Burak": [
        "Selam yakışıklı spiker... yine mikrofona konuşuyorsun ama fantasy kadron susuyor mk 😂",
        "Burak, ekran yüzü olabilirsin ama bu ligde veto gözsüz yapılmaz knk.",
        "Spikerim benim… geçen haftaki takas önerinle CNN Türk’ü kapatırdım yeminle.",
        "Sesin güzel de... veto konusu açılınca modem sesi çıkartıyorsun bro 📡"
    ],
    "Dodocan": [
        "Dodocan sen olduğun sürece bu ligin goygoy seviyesi hep elit kalacak.",
        "Sana selam vermek ayrı, seni veto'dan korumak apayrı knk.",
        "Dodocan... bu ligin lider ruhu sensin, Burak spikerliğe devam etsin."
    ]
}

def kisiye_ozel_cevap(kisi_adi):
    if kisi_adi in SPECIAL_REPLIES:
        return random.choice(SPECIAL_REPLIES[kisi_adi])
    else:
        return None
