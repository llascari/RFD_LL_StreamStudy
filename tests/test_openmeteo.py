import json
import unittest
from datetime import date, datetime, timezone

from streamstudy.providers.openmeteo import (
    OpenMeteoProvider,
    parse_archive_payload,
    parse_payload,
    parse_weather_payload,
)
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


class WeatherTest(unittest.TestCase):
    def test_daily_weather_payload(self):
        payload = json.loads(fixture("openmeteo_weather.json"))
        weather = parse_weather_payload(payload)
        self.assertEqual(len(weather.daily), 16)
        first = weather.daily[0]
        self.assertIsNotNone(first.mean_c)
        self.assertIsNotNone(first.sunshine_hours)
        self.assertGreaterEqual(first.sunshine_hours, 0.0)
        self.assertIsNotNone(first.cloud_pct)

    def test_provider_requests_temperature_and_sunshine(self):
        class Client:
            def __init__(self):
                self.params = None

            def get_json(self, url, params=None):
                self.params = params
                return json.loads(fixture("openmeteo_weather.json"))

        client = Client()
        data = OpenMeteoProvider(client).fetch_weather(43.14, -77.51, past_days=7)
        self.assertEqual(len(data.daily), 16)
        self.assertIn("temperature_2m_mean", client.params["daily"])
        self.assertIn("sunshine_duration", client.params["daily"])
        self.assertEqual(client.params["past_days"], 7)
        self.assertEqual(client.params["timeformat"], "unixtime")


class ArchiveTest(unittest.TestCase):
    def test_archive_daily_days(self):
        payload = json.loads(fixture("openmeteo_archive.json"))
        archive = parse_archive_payload(payload)
        self.assertEqual(len(archive.daily), 21)
        day, millimetres = archive.daily[0]
        self.assertEqual(day, date(2024, 1, 1))
        self.assertGreaterEqual(millimetres, 0.0)
        self.assertEqual(archive.timezone, "America/New_York")

    def test_provider_archive_parameters(self):
        client = StaticClient()
        provider = OpenMeteoProvider(client)
        provider.fetch_archive(43.14, -77.51, date(2024, 1, 1), date(2024, 1, 31))
        url, params = client.calls[-1]
        self.assertIn("archive-api.open-meteo.com", url)
        self.assertEqual(params["start_date"], "2024-01-01")
        self.assertEqual(params["end_date"], "2024-01-31")
        self.assertIn("precipitation_sum", params["daily"])
        self.assertIn("temperature_2m_mean", params["daily"])


if __name__ == "__main__":
    unittest.main()
