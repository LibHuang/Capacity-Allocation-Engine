# Import Packages
import pandas as pd
import os
import datetime
from data_loader import load_infrastructure_data
from warehouse import WarehouseNetwork
from cleanup import clean_inventory_data
from fulfill_orders import fulfill_orders

# Output file
datestr = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')
outfile = os.path.join(tmpdir, "AllocationFulfillment.xlsx")

# Load configuration files
fulfillment_centers, regional_centers, warehouse_specs, expansion_mapping = load_infrastructure_data('./config')

# Load demand files
demand_orders_today = load_demand_data('./config')

# EDA Cleanup
fulfillment_centers = clean_inventory_data(fulfillment_centers)
regional_centers = clean_inventory_data(regional_centers)
demand_orders_today = clean_inventory_data(demand_orders_today)

# Real Time Data Collection
warehouse = WarehouseNetwork(fulfillment_centers, regional_centers, warehouse_specs)
capacity_data = warehouse.get_capacity_metrics()
utilization = warehouse.get_utilization()

# Fulfill orders
results = fulfill_orders(warehouse, demand_orders_today, capacity_data)

# Export
results.to_excel(outfile)