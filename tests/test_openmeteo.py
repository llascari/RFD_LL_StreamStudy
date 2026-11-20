import json
import unittest
from datetime import datetime, timezone

from streamstudy.providers.openmeteo import OpenMeteoProvider, parse_payload
from tests.support import StaticClient, fixture


class OpenMeteoTest(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(fixture("openmeteo.json"))
        self.data = parse_payload(self.payload)

    def test_hourly_steps(self):
        self.assertEqual(len(self.data.hourly), 6)
        moment, amount, probability = self.data.hourly[0]
        self.assertIsInstance(moment, datetime)
        self.assertEqual(moment.tzinfo, timezone.utc)
        self.assertEqual(amount, 0.0)
        self.assertEqual(probability, 0)

    def test_daily_dates_use_local_offset(self):
        self.assertEqual(len(self.data.daily), 3)
        offset = self.payload["utc_offset_seconds"]
        for (day, _value), stamp in zip(self.data.daily, self.payload["daily"]["time"]):
            expected = datetime.fromtimestamp(int(stamp) + offset, tz=timezone.utc).date()
            self.assertEqual(day, expected)

    def test_metadata(self):
        self.assertEqual(self.data.timezone, "America/New_York")

    def test_provider_parameters(self):
        client = StaticClient()
        provider = OpenMeteoProvider(client)
        provider.fetch(43.1448, -77.512, past_days=7, forecast_days=2)
        _url, params = client.calls[-1]
        self.assertEqual(params["past_days"], 7)
        self.assertEqual(params["forecast_days"], 2)
        self.assertEqual(params["timezone"], "auto")
        self.assertEqual(params["timeformat"], "unixtime")
        self.assertIn("precipitation", params["hourly"])


if __name__ == "__main__":
    unittest.main()
