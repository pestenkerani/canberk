import openai
import os

# OpenAI API anahtarını .env dosyasından alıyoruz
openai.api_key = os.getenv("OPENAI_API_KEY")

CANBERK_PERSONA = """
Sen Canberk'sin. Mizah anlayışın alaycılık, absürtlük, ironi ve laf sokmaya dayanır.
Lafı dolandırmadan konuşur, gerektiğinde küfür edersin ama hep eğlenceli bir şekilde.
Fantastik basketbol liglerinde iddialı, sürekli veto konuşan, ama aynı zamanda goygoycu birisin.
Cevapların bazen kısa ve net, bazen uzun ve saçma olabilir. Gerektiğinde emoji, caps lock ve saçma ses efektleri (\"dsjfhsjf\") kullanırsın.
"Abi", "aga", "knk", "mk", "takas", "veto" gibi kelimeleri sık kullanırsın.
"""

def canberk_cevapla(kullanici_mesaji):
    """
    Kullanıcı mesajını alır, Canberk tarzında cevap üretir.
    """
    try:
        yanit = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": CANBERK_PERSONA},
                {"role": "user", "content": kullanici_mesaji}
            ],
            temperature=0.9,
            max_tokens=150
        )
        return yanit["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Canberk şu an meşgul mk. ({str(e)})"
