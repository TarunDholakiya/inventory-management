import random
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

# Restocking models (separate from PurchaseOrder/CreatePurchaseOrderRequest above, which
# are unwired to any route - see the "Known gap" note in CLAUDE.md)
class RestockOrderItem(BaseModel):
    sku: str
    name: str
    category: str
    quantity: int
    unit_cost: float
    line_total: float
    score: float  # priority score that ranked this item, surfaced for transparency

class RestockRecommendation(BaseModel):
    budget: float
    items: List[RestockOrderItem]
    total_cost: float
    remaining_budget: float
    item_count: int

class CreateRestockOrderRequest(BaseModel):
    budget: float

class RestockOrder(BaseModel):
    id: str
    order_number: str
    budget: float
    items: List[RestockOrderItem]
    total_cost: float
    lead_time_days: int
    order_date: str
    expected_delivery: str
    status: str

# Runtime-only store for submitted restocking orders (not JSON-backed, resets on restart -
# consistent with the rest of this app's no-persistence model)
restock_orders: List[dict] = []

# Restock recommendation scoring is a 50/50 blend of demand growth and low-stock urgency;
# named as constants so the weighting is easy to tune without touching the algorithm below.
RESTOCK_WEIGHT_DEMAND = 0.5
RESTOCK_WEIGHT_STOCK = 0.5

def build_recommendation(budget: float) -> dict:
    """Score demand-forecast items by growth + low-stock urgency, then greedily fill the
    budget with the highest-scored items first. Shared by both restocking endpoints so the
    POST re-derives (rather than trusts) whatever budget the client submits."""
    inventory_by_sku = {item["sku"]: item for item in inventory_items}

    candidates = []
    for forecast in demand_forecasts:
        item = inventory_by_sku.get(forecast["item_sku"])
        if not item:
            continue

        current_demand = forecast["current_demand"]
        forecasted_demand = forecast["forecasted_demand"]
        quantity_on_hand = item["quantity_on_hand"]
        reorder_point = item["reorder_point"]

        growth_pct = (forecasted_demand - current_demand) / max(current_demand, 1)
        growth_score = max(0, growth_pct)

        urgency_pct = (reorder_point - quantity_on_hand) / max(reorder_point, 1)
        urgency_score = max(0, urgency_pct)

        combined_score = RESTOCK_WEIGHT_DEMAND * growth_score + RESTOCK_WEIGHT_STOCK * urgency_score

        # Desired quantity: close the gap to forecasted demand first; if demand is already
        # covered, fall back to just clearing the reorder-point shortfall. An item needing
        # neither is excluded - it doesn't need restocking regardless of its score.
        desired_qty = max(forecasted_demand - quantity_on_hand, 0)
        if desired_qty == 0:
            desired_qty = max(reorder_point - quantity_on_hand, 0)
        if desired_qty == 0:
            continue

        candidates.append({
            "sku": item["sku"],
            "name": item["name"],
            "category": item["category"],
            "unit_cost": item["unit_cost"],
            "desired_qty": desired_qty,
            "urgency_score": urgency_score,
            "combined_score": combined_score,
        })

    # Tie-break on urgency then SKU so results are deterministic across identical scores.
    candidates.sort(key=lambda c: (-c["combined_score"], -c["urgency_score"], c["sku"]))

    remaining = budget
    items = []
    # Walk the full sorted list rather than stopping at the first unaffordable item, so a
    # cheaper lower-priority item can still use whatever budget is left over.
    for candidate in candidates:
        max_affordable = int(remaining // candidate["unit_cost"])
        qty = min(candidate["desired_qty"], max_affordable)
        if qty >= 1:
            line_total = round(qty * candidate["unit_cost"], 2)
            items.append(RestockOrderItem(
                sku=candidate["sku"],
                name=candidate["name"],
                category=candidate["category"],
                quantity=qty,
                unit_cost=candidate["unit_cost"],
                line_total=line_total,
                score=round(candidate["combined_score"], 4),
            ))
            remaining -= line_total

    total_cost = round(budget - remaining, 2)
    return {
        "budget": budget,
        "items": items,
        "total_cost": total_cost,
        "remaining_budget": round(remaining, 2),
        "item_count": len(items),
    }

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/restocking/recommend", response_model=RestockRecommendation)
def get_restock_recommendation(budget: float):
    """Read-only: recommend items to restock for a given budget (called live as the slider moves)."""
    if budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be greater than 0")
    return build_recommendation(budget)

@app.post("/api/restocking/orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Place a restocking order. Re-derives the recommendation server-side from the
    submitted budget rather than trusting any client-supplied item list."""
    if request.budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be greater than 0")
    rec = build_recommendation(request.budget)
    if not rec["items"]:
        raise HTTPException(status_code=400, detail="Budget too low to recommend any items")

    # Lead time is randomly assigned within a realistic range per the product decision -
    # there's no real supplier/logistics data in this demo to derive it from.
    lead_time_days = random.randint(5, 14)
    order_date = datetime.now()
    expected_delivery = order_date + timedelta(days=lead_time_days)
    order = {
        "id": str(uuid.uuid4()),
        "order_number": f"RST-{len(restock_orders) + 1:04d}",
        "budget": request.budget,
        "items": rec["items"],
        "total_cost": rec["total_cost"],
        "lead_time_days": lead_time_days,
        "order_date": order_date.isoformat(),
        "expected_delivery": expected_delivery.isoformat(),
        "status": "Processing",
    }
    restock_orders.append(order)
    return order

@app.get("/api/restocking/orders", response_model=List[RestockOrder])
def get_restock_orders():
    """List all submitted restocking orders, for the Orders tab's Submitted Orders section."""
    return restock_orders

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
