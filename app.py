from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from canberk_core import canberk_cevapla
from dotenv import load_dotenv
import os

# Ortam değişkenlerini yükle
load_dotenv()

app = Flask(__name__)

@app.route("/sms", methods=["POST"])
def sms_cevapla():
    gelen_mesaj = request.form.get("Body")
    gonderen_numara = request.form.get("From")

    cevap = canberk_cevapla(gelen_mesaj)

    yanit = MessagingResponse()
    yanit.message(cevap)

    print(f"[Mesaj geldi] {gonderen_numara}: {gelen_mesaj}\n[Canberk cevabi]: {cevap}")
    return str(yanit)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

