from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from canberk_core import canberk_cevapla
from dotenv import load_dotenv
import os
import sys
sys.path.append('/opt/render/project/src')

# Ortam değişkenleriniyükle
load_dotenv()

# Kullanıcı numaralarını ve isimlerini eşleştirme
NUMARA_ILE_KISILER = {
    "+905434325351": "Burak",
    "+905075450909": "Kutaycan",  # Kutay'ın numarasını buraya ekleyin
    "+905350224775": "Dodocan"   # Dodocan'ın numarasını buraya ekleyin
}

app = Flask(__name__)

@app.route("/sms", methods=["POST"])
def sms_cevapla():
    # WhatsApp'tan gelen mesajı al
    gelen_mesaj = request.form.get("Body")
    gonderen_numara = request.form.get("From")

    # Gönderen numaraya göre kişi adı al
    gonderen_adi = NUMARA_ILE_KISILER.get(gonderen_numara)

    # Canberk'ten cevap üret
    cevap = canberk_cevapla(gelen_mesaj, gonderen_adi)

    # Yanıtı oluştur
    yanit = MessagingResponse()
    yanit.message(cevap)

    print(f"[Mesaj geldi] {gonderen_numara}: {gelen_mesaj}\n[Canberk cevabi]: {cevap}")
    return str(yanit)

if __name__ == "__main__":
    # Render'ın belirlediği PORT'u kullan
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
