"""
Tests for restocking API endpoints.
"""
import pytest


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_get_recommendation_returns_200_and_structure(self, client):
        """Test getting a recommendation returns the expected shape."""
        response = client.get("/api/restocking/recommend?budget=25000")
        assert response.status_code == 200

        data = response.json()
        assert "budget" in data
        assert "items" in data
        assert "total_cost" in data
        assert "remaining_budget" in data
        assert "item_count" in data
        assert isinstance(data["items"], list)

    def test_recommendation_items_never_exceed_budget(self, client):
        """Test that total_cost never exceeds the requested budget, across a range of budgets."""
        for budget in [1000, 10000, 50000, 150000]:
            response = client.get(f"/api/restocking/recommend?budget={budget}")
            assert response.status_code == 200

            data = response.json()
            assert data["total_cost"] <= budget
            assert sum(item["line_total"] for item in data["items"]) <= budget

    def test_recommendation_zero_budget_returns_400(self, client):
        """Test that a zero budget is rejected."""
        response = client.get("/api/restocking/recommend?budget=0")
        assert response.status_code == 400

    def test_recommendation_negative_budget_returns_400(self, client):
        """Test that a negative budget is rejected."""
        response = client.get("/api/restocking/recommend?budget=-100")
        assert response.status_code == 400

    def test_recommendation_missing_budget_param_returns_422(self, client):
        """Test that budget is a required query parameter."""
        response = client.get("/api/restocking/recommend")
        assert response.status_code == 422

    def test_recommendation_higher_budget_recommends_more_or_equal_items(self, client):
        """Test that a larger budget never recommends fewer items than a smaller one."""
        small = client.get("/api/restocking/recommend?budget=1000").json()
        large = client.get("/api/restocking/recommend?budget=50000").json()
        assert large["item_count"] >= small["item_count"]

    def test_recommendation_items_reference_real_inventory_skus(self, client):
        """Test that every recommended SKU exists in the inventory."""
        inventory_skus = {item["sku"] for item in client.get("/api/inventory").json()}

        response = client.get("/api/restocking/recommend?budget=100000")
        data = response.json()
        assert len(data["items"]) > 0

        for item in data["items"]:
            assert item["sku"] in inventory_skus

    def test_recommendation_prioritizes_low_stock_and_rising_demand(self, client):
        """Test that at a small budget, the highest-priority item (corrected TMP-201,
        which has the largest combined growth+urgency score) is recommended first."""
        response = client.get("/api/restocking/recommend?budget=2000")
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["sku"] == "TMP-201"

    def test_place_order_creates_order_with_lead_time_in_range(self, client):
        """Test that placing an order assigns a lead time within the documented range."""
        response = client.post("/api/restocking/orders", json={"budget": 30000})
        assert response.status_code == 201

        data = response.json()
        assert 5 <= data["lead_time_days"] <= 14

    def test_place_order_expected_delivery_matches_lead_time(self, client):
        """Test that expected_delivery is order_date plus lead_time_days."""
        from datetime import datetime

        response = client.post("/api/restocking/orders", json={"budget": 30000})
        data = response.json()

        order_date = datetime.fromisoformat(data["order_date"])
        expected_delivery = datetime.fromisoformat(data["expected_delivery"])
        delta_days = (expected_delivery - order_date).days
        assert delta_days == data["lead_time_days"]

    def test_place_order_too_low_budget_returns_400(self, client):
        """Test that a budget too low to afford any item is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1})
        assert response.status_code == 400

    def test_place_order_ignores_client_supplied_items(self, client):
        """Test that the server recomputes items from budget, ignoring any extraneous
        client-supplied fields (the endpoint's Pydantic model only accepts budget)."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 30000, "items": [{"sku": "FAKE-999", "quantity": 999999}]},
        )
        assert response.status_code == 201

        data = response.json()
        for item in data["items"]:
            assert item["sku"] != "FAKE-999"

    def test_get_restock_orders_returns_previously_placed_orders(self, client):
        """Test that a placed order shows up in the list endpoint."""
        placed = client.post("/api/restocking/orders", json={"budget": 20000}).json()

        response = client.get("/api/restocking/orders")
        assert response.status_code == 200

        order_ids = {order["id"] for order in response.json()}
        assert placed["id"] in order_ids

    def test_restock_order_total_cost_matches_items_sum(self, client):
        """Test that total_cost equals the sum of each item's line_total."""
        response = client.post("/api/restocking/orders", json={"budget": 40000})
        data = response.json()

        items_sum = sum(item["line_total"] for item in data["items"])
        assert abs(data["total_cost"] - items_sum) < 0.01

    def test_demand_forecasts_reference_real_inventory_skus(self, client):
        """Regression test for the demand_forecasts.json data fix: every forecast's
        item_sku must exist in inventory, or restocking recommendations silently skip it."""
        inventory_skus = {item["sku"] for item in client.get("/api/inventory").json()}

        response = client.get("/api/demand")
        data = response.json()
        assert len(data) > 0

        for forecast in data:
            assert forecast["item_sku"] in inventory_skus
