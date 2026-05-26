import logging
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SmsProvider(Protocol):
    async def send_otp(self, phone_number: str, code: str) -> None: ...


class ConsoleSmsProvider:
    async def send_otp(self, phone_number: str, code: str) -> None:
        logger.info("[SMS/console] OTP for %s: %s", phone_number, code)


class TwilioSmsProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number

    async def send_otp(self, phone_number: str, code: str) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        body = f"Your verification code is {code}. It expires in {settings.OTP_TTL_MIN} minutes."
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                data={"From": self._from_number, "To": phone_number, "Body": body},
                auth=(self._account_sid, self._auth_token),
            )
            if resp.status_code >= 400:
                logger.error("Twilio send failed: %s %s", resp.status_code, resp.text)
                raise RuntimeError("SMS_SEND_FAILED")


def get_sms_provider() -> SmsProvider:
    provider = settings.SMS_PROVIDER.lower()
    if provider == "twilio":
        if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_FROM_NUMBER):
            raise RuntimeError("Twilio is configured as SMS_PROVIDER but credentials are missing")
        return TwilioSmsProvider(
            settings.TWILIO_ACCOUNT_SID,
            settings.TWILIO_AUTH_TOKEN,
            settings.TWILIO_FROM_NUMBER,
        )
    return ConsoleSmsProvider()
