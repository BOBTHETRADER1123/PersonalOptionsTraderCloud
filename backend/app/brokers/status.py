import os

BROKER_FIELDS = {
    "Dhan": ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN"),
    "Kotak Neo": ("KOTAK_CONSUMER_KEY", "KOTAK_MOBILE_NUMBER", "KOTAK_UCC", "KOTAK_MPIN"),
    "5paisa": ("FIVEPAISA_APP_KEY", "FIVEPAISA_CLIENT_CODE", "FIVEPAISA_ACCESS_TOKEN"),
}


def broker_status() -> list[dict]:
    result = []
    for broker, names in BROKER_FIELDS.items():
        missing = [name for name in names if not os.getenv(name)]
        if broker == "Kotak Neo" and not (os.getenv("KOTAK_TOTP") or os.getenv("KOTAK_TOTP_SECRET")):
            missing.append("KOTAK_TOTP_SECRET")
        result.append({"broker": broker, "configured": not missing, "status": "Needs credentials" if missing else "Configured; account verification required", "missing": missing})
    return result
