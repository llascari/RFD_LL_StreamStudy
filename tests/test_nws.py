import json
import unittest

from streamstudy.providers.nws import (
    NwsProvider,
    parse_location,
    parse_observations,
    parse_periods,
    parse_qpf,
    parse_stations,
)
from tests.support import StaticClient, fixture


class ParsingTest(unittest.TestCase):
    def test_points_grid(self):
        location = parse_location(json.loads(fixture("nws_points.json")))
        self.assertEqual((location.grid_id, location.grid_x, location.grid_y), ("BUF", 80, 64))
        self.assertEqual(location.timezone, "America/New_York")
        self.assertTrue(location.city)
        self.assertEqual(location.state, "NY")

    def test_stations_sorted_by_distance(self):
        stations = parse_stations(json.loads(fixture("nws_stations.json")))
        self.assertEqual(len(stations), 3)
        self.assertEqual(stations[0].identifier, "KGVQ")
        self.assertAlmostEqual(stations[0].distance_km, 14.05, places=1)
        distances = [station.distance_km for station in stations]
        self.assertEqual(distances, sorted(distances))

    def test_observation_unit_conversion(self):
        payload = {
            "features": [
                {
                    "properties": {
                        "timestamp": "2026-11-20T12:00:00+00:00",
                        "precipitationLastHour": {"unitCode": "wmoUnit:mm", "value": 12.7},
                        "temperature": {"unitCode": "wmoUnit:degC", "value": 8.0},
                    }
                },
                {
                    "properties": {
                        "timestamp": "2026-11-20T11:00:00+00:00",
                        "precipitationLastHour": {"unitCode": "wmoUnit:mm", "value": None},
                        "temperature": {"unitCode": "wmoUnit:degC", "value": 7.5},
                    }
                },
            ]
        }
        precip, temperature = parse_observations(payload)
        self.assertIsNotNone(precip)
        self.assertEqual(len(precip.samples), 1)
        self.assertAlmostEqual(precip.samples[0].value, 0.5)
        self.assertEqual(temperature.units, "\u00b0C")
        self.assertEqual([sample.value for sample in temperature.samples], [7.5, 8.0])

    def test_hourly_periods(self):
        periods = parse_periods(json.loads(fixture("nws_hourly.json")))
        self.assertEqual(len(periods), 3)
        self.assertEqual(periods[0].temperature, 54)
        self.assertEqual(periods[0].temperature_unit, "\u00b0F")
        self.assertEqual(periods[0].precip_probability, 0)
        self.assertEqual(periods[0].short, "Sunny")

    def test_daily_periods_and_details(self):
        periods = parse_periods(json.loads(fixture("nws_daily.json")))
        self.assertEqual(len(periods), 4)
        self.assertTrue(any(period.detailed for period in periods))


class QpfTest(unittest.TestCase):
    def test_duration_parsing(self):
        payload = {
            "properties": {
                "quantitativePrecipitation": {
                    "uom": "wmoUnit:mm",
                    "values": [
                        {"validTime": "2026-11-20T14:00:00+00:00/PT6H", "value": 12.7},
                        {"validTime": "2026-11-20T20:00:00+00:00/P1D", "value": 0},
                        {"validTime": "2026-11-21T02:00:00+00:00/PT6H", "value": None},
                    ],
                }
            }
        }
        qpf = parse_qpf(payload)
        self.assertEqual(len(qpf), 3)
        centres = [moment.isoformat() for moment, _ in qpf]
        self.assertEqual(centres, sorted(centres))
        first_moment, first_inches = qpf[0]
        self.assertAlmostEqual(first_inches, 0.5)
        self.assertEqual(first_moment.hour, 17)  # 14:00 + 3 h, in UTC

    def test_qpf_fixture(self):
        qpf = parse_qpf(json.loads(fixture("nws_grid.json")))
        self.assertEqual(len(qpf), 16)
        self.assertTrue(all(value >= 0 for _moment, value in qpf))


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.client = StaticClient()
        self.provider = NwsProvider(self.client)

    def test_location_and_station_chain(self):
        location = self.provider.location(43.1448, -77.512)
        self.assertTrue(location.stations_url)
        stations = self.provider.nearest_stations(location, limit=2)
        self.assertEqual(len(stations), 2)
        self.assertEqual(stations[0].network, "NWS")

    def test_observations_request_window(self):
        precip, temperature = self.provider.observations("KROC", hours=24)
        url, params = self.client.calls[-1]
        self.assertTrue(url.endswith("/stations/KROC/observations"))
        self.assertIn("start", params)
        self.assertIn("end", params)
        self.assertEqual(params["limit"], 500)
        self.assertIsNotNone(temperature)

    def test_forecasts(self):
        location = self.provider.location(43.1448, -77.512)
        hourly = self.provider.hourly_forecast(location, limit=2)
        daily = self.provider.daily_forecast(location)
        self.assertEqual(len(hourly), 2)
        self.assertEqual(len(daily), 4)

    def test_qpf_request(self):
        location = self.provider.location(43.1448, -77.512)
        qpf = self.provider.qpf(location)
        url, _params = self.client.calls[-1]
        self.assertIn("/gridpoints/BUF/80,64", url)
        self.assertEqual(len(qpf), 16)


if __name__ == "__main__":
    unittest.main()
