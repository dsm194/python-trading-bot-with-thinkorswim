import os

import requests

import config_loader  # noqa: F401


class PushNotification:

    def __init__(self, device_id, logger):
        self.url = "https://www.pushsafer.com/api"
        self.api_key = os.getenv("PUSH_API_KEY")
        self.post_fields = {
            "t": "TOS Trading Bot",
            "s": 0,
            "v": 1,
            "i": 1,
            "c": "#E94B3C",
            "d": device_id,
            "ut": "TOS Trading Bot",
            "k": self.api_key,
        }
        self.logger = logger

    def send(self, notification):
        """Send a notification without allowing Pushsafer to stall the bot."""
        if not self.api_key or not self.post_fields["d"]:
            self.logger.warning(
                "Pushsafer is not configured; notification was not sent."
            )
            return False

        try:
            payload = {**self.post_fields, "m": notification}
            response = requests.post(self.url, data=payload, timeout=10)
            response_data = response.json()

            if response_data.get("success") == "message transmitted":
                self.logger.info("Pushsafer notification sent.")
                return True

            self.logger.warning(
                "Pushsafer notification failed: %s",
                response_data.get("error", "unknown response"),
            )
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("Pushsafer notification error: %s", exc)

        return False
