def fulfill_orders(centers, orders, capacity_model):

    # ============================================================
    # STEP 1 — INITIALIZE TRACKING COLUMNS
    # ============================================================
    centers['NumberofOrders']           = 0
    centers['RequiredShelfSpace']       = 0
    centers['RequiredPickingLabor']     = 0
    centers['RequiredPackaging']        = 0
    centers['CenterExpansionRequired']  = 0
    centers['NewCenter']                = 'No'
    centers['TempRemainingShelfSpace']  = centers['RemainingShelfSpace']
    centers['TempRemainingPickingLabor']= centers['RemainingPickingLabor']
    centers['TempRemainingPackaging']   = centers['RemainingPackaging']

    # ============================================================
    # STEP 2 — CAPACITY BUFFER
    # Never fill a center to 100%
    # Reserves room for returns and seasonal surges
    # ============================================================
    CAPACITY_BUFFER = 0.80  # only use 80% of available capacity

    # ============================================================
    # STEP 3 — SLA DEADLINES
    # Every segment has a delivery promise to keep
    # ============================================================
    SLA_HOURS = {
        'PREMIER'      : 24,    # next day
        'STANDARD'     : 72,    # 3 days
        'WHOLESALE'    : 168,   # 7 days
        'INTERNATIONAL': 336    # 14 days
    }
    orders['SLA_Hours'] = orders['CustomerSegment'].map(SLA_HOURS)

    # ============================================================
    # STEP 4 — PRIORITY SCORING
    # VIP orders jump the queue
    # ============================================================
    PRIORITY_SCORES = {
        'HAUTE_COUTURE' : 100,
        'VIC'           : 80,
        'PREMIER'       : 60,
        'STANDARD'      : 40,
        'WHOLESALE'     : 20
    }
    orders['PriorityScore'] = orders['CustomerSegment'].map(PRIORITY_SCORES)

    # ============================================================
    # STEP 5 — SORT
    # Priority first, then resource requirements
    # High priority orders get best available centers
    # ============================================================
    orders = orders.sort_values(
        ['PriorityScore', 'Region', 'CustomerSegment',
         'CenterType', 'ItemSize', 'PickingLabor'],
        ascending=[False, True, True, True, True, True]
        #           ↑ priority descending — highest first
    )
    centers = centers.sort_values(['TotalCapacity'], ascending=False)

    # Initialize output columns
    orders['Target_Region']         = np.nan
    orders['Target_FulfillmentHub'] = np.nan
    orders['Target_Center']         = np.nan
    orders['Fulfilled']             = 'No'
    orders['SLA_Met']               = 'No'   # ← track SLA outcome

    orders['Target_Region']         = orders['Target_Region'].astype("string")
    orders['Target_FulfillmentHub'] = orders['Target_Region'].astype("string")
    orders['Target_Center']         = orders['Target_Region'].astype("string")

    # ============================================================
    # STEP 6 — CORE PLACEMENT LOOP
    # ============================================================
    for i, order in orders.iterrows():

        while True:
            break_while = False
            loopcount   = 0

            for j, center in centers.iterrows():
                mask = (
                    (centers['Region']          == order['Region']) &
                    (centers['CustomerSegment'] == order['CustomerSegment']) &
                    (centers['CenterType']      == order['CenterType'])
                )
                row_match  = centers[mask]
                totcenters = len(row_match)

                if (
                    order['Region']          == center['Region'] and
                    order['CustomerSegment'] == center['CustomerSegment'] and
                    order['CenterType']      == center['CenterType']
                ):
                    loopcount += 1
                    orders.loc[i, 'Target_Region']         = center['Region']
                    orders.loc[i, 'Target_FulfillmentHub'] = center['FulfillmentHub']

                    # ------------------------------------------------
                    # STATE 1: CENTER HAS CAPACITY — FULFILL THE ORDER
                    # Capacity Buffer applied here — never fill to 100%
                    # SLA check applied here — center must meet deadline
                    # ------------------------------------------------
                    if (
                        # CAPACITY BUFFER CHECK ← ADD #1 APPLIED HERE
                        (center['TempRemainingShelfSpace']   * CAPACITY_BUFFER - center['RequiredShelfSpace']   >= order['ItemSize']) and
                        (center['TempRemainingPickingLabor'] * CAPACITY_BUFFER - center['RequiredPickingLabor'] >= order['PickingLabor']) and
                        (center['TempRemainingPackaging']    * CAPACITY_BUFFER - center['RequiredPackaging']    >= order['PackagingUnits']) and
                        # SLA CHECK ← ADD #2 APPLIED HERE
                        (center['AvgProcessingHours'] <= order['SLA_Hours'])
                    ):
                        # Reserve capacity
                        centers.at[j, 'RequiredShelfSpace']   += order['ItemSize']
                        centers.at[j, 'RequiredPickingLabor'] += order['PickingLabor']
                        centers.at[j, 'RequiredPackaging']    += order['PackagingUnits']

                        # Record fulfillment
                        orders.loc[i, 'Target_Center'] = center['CenterID']
                        orders.loc[i, 'Fulfilled']     = 'Yes'
                        orders.loc[i, 'SLA_Met']       = 'Yes'  # ← SLA confirmed
                        centers.loc[j, 'NumberofOrders'] = center['NumberofOrders'] + 1
                        break_while = True
                        break

                    # ------------------------------------------------
                    # STATE 2: CENTER FULL BUT CAN EXPAND
                    # ------------------------------------------------
                    elif (
                        loopcount >= totcenters and
                        (
                            ((center['TotalCapacity'] + center['CenterExpansionRequired']) < 16 and center['NewCenter'] == 'No') or
                            ((center['TotalCapacity'] + center['CenterExpansionRequired']) <= 16 and center['NewCenter'] == 'Yes')
                        ) and
                        break_while is False
                    ):
                        if center['CenterLayout'] == 'MULTI_SITE':
                            stationaddcount = 2
                        else:
                            stationaddcount = 1

                        centermodel     = center['CenterModel']
                        modelcapacity   = capacity_model[capacity_model['CenterModel'] == centermodel]
                        addshelfspace   = modelcapacity['ShelfSpace'].iloc[0]
                        addpickinglabor = modelcapacity['PickingLabor'].iloc[0]
                        addpackaging    = modelcapacity['PackagingUnits'].iloc[0]

                        centers.loc[j, 'CenterExpansionRequired']   = center['CenterExpansionRequired'] + stationaddcount
                        centers.loc[j, 'TempRemainingShelfSpace']   = center['TempRemainingShelfSpace'] + addshelfspace
                        centers.loc[j, 'TempRemainingPickingLabor'] = center['TempRemainingPickingLabor'] + addpickinglabor
                        centers.loc[j, 'TempRemainingPackaging']    = center['TempRemainingPackaging'] + addpackaging
                        break

                    # ------------------------------------------------
                    # STATE 3: CENTER AT MAX — PROVISION NEW CENTER
                    # ------------------------------------------------
                    elif (
                        loopcount >= totcenters and
                        (center['TotalCapacity'] + center['CenterExpansionRequired']) >= 16 and
                        break_while is False
                    ):
                        centermodel     = center['CenterModel']
                        modelcapacity   = capacity_model[capacity_model['CenterModel'] == centermodel]
                        addshelfspace   = modelcapacity['ShelfSpace'].iloc[0]
                        addpickinglabor = modelcapacity['PickingLabor'].iloc[0]
                        addpackaging    = modelcapacity['PackagingUnits'].iloc[0]

                        hub         = center['FulfillmentHub']
                        hubnamedf   = centers[centers['FulfillmentHub'] == hub]
                        hubnamedf   = hubnamedf[['FulfillmentHub', 'CenterID']]
                        hubnamedf['CenterNumber'] = hubnamedf['CenterID'].apply(
                            lambda x: int(re.search(r'\d+', x).group(0))
                        )
                        max_center_number = hubnamedf['CenterNumber'].max()
                        newcentername     = 'CENTER-' + str(max_center_number + 1)

                        newcenterdict = {}

                        if center['CenterLayout'] == 'MULTI_SITE':
                            stationaddcount = 2
                            addshelfspace   = addshelfspace   * (stationaddcount / 2)
                            addpickinglabor = addpickinglabor * (stationaddcount / 2)
                            addpackaging    = addpackaging    * (stationaddcount / 2)
                        else:
                            stationaddcount = 2
                            addshelfspace   = addshelfspace   * stationaddcount
                            addpickinglabor = addpickinglabor * stationaddcount
                            addpackaging    = addpackaging    * stationaddcount

                        newcenterdict = {
                            'CenterID'               : newcentername,
                            'NewCenter'              : 'Yes',
                            'RemainingShelfSpace'    : addshelfspace,
                            'RemainingPickingLabor'  : addpickinglabor,
                            'RemainingPackaging'     : addpackaging,
                            'CommittedSpace'         : 0,
                            'CenterLayout'           : center['CenterLayout'],
                            'CenterModel'            : center['CenterModel'],
                            'TotalCapacity'          : stationaddcount,
                            'CenterExpansionRequired': stationaddcount,
                            'CenterType'             : center['CenterType'],
                            'CustomerSegment'        : center['CustomerSegment'],
                            'Region'                 : center['Region'],
                            'FulfillmentHub'         : center['FulfillmentHub'],
                            'NetworkZone'            : center['NetworkZone'],
                            'AvgProcessingHours'     : center['AvgProcessingHours'],  # ← inherit SLA capability
                            'RequiredShelfSpace'     : 0,
                            'RequiredPickingLabor'   : 0,
                            'RequiredPackaging'      : 0,
                            'NumberofOrders'         : 0,
                            'TotalAllocatedLabor'    : 0,
                            'TotalAllocatedSpace'    : 0
                        }

                        newcenterdf = pd.DataFrame([newcenterdict])
                        newcenterdf['TempRemainingShelfSpace']   = newcenterdf['RemainingShelfSpace']
                        newcenterdf['TempRemainingPickingLabor'] = newcenterdf['RemainingPickingLabor']
                        newcenterdf['TempRemainingPackaging']    = newcenterdf['RemainingPackaging']
                        centers = pd.concat([centers, newcenterdf], ignore_index=True)
                        centers = centers.sort_values(['TotalCapacity'], ascending=False)
                        break

            if break_while:
                break

    # ============================================================
    # STEP 7 — POST FULFILLMENT CLEANUP
    # ============================================================
    centers.loc[centers['NewCenter'] == 'Yes', 'RemainingShelfSpace']    = centers['TempRemainingShelfSpace']
    centers.loc[centers['NewCenter'] == 'Yes', 'RemainingPickingLabor']  = centers['TempRemainingPickingLabor']
    centers.loc[centers['NewCenter'] == 'Yes', 'RemainingPackaging']     = centers['TempRemainingPackaging']
    centers.loc[centers['NewCenter'] == 'Yes', 'UsableCapacityThreshold']= centers['TempRemainingShelfSpace'] * 0.60
    centers.loc[centers['NewCenter'] == 'Yes', 'TotalCapacity']          = 0

    centers['ShelfSpaceExpansionRequired']   = (centers.RequiredShelfSpace   - centers.RemainingShelfSpace).clip(lower=0)
    centers['PickingLaborExpansionRequired'] = (centers.RequiredPickingLabor - centers.RemainingPickingLabor).clip(lower=0)
    centers['PackagingExpansionRequired']    = (centers.RequiredPackaging    - centers.RemainingPackaging).clip(lower=0)

    centers['APRemainingShelfSpace']   = centers.RemainingShelfSpace   + centers.RequiredShelfSpace
    centers['APRemainingPickingLabor'] = centers.RemainingPickingLabor + centers.RequiredPickingLabor
    centers['APRemainingPackaging']    = centers.RemainingPackaging    + centers.RequiredPackaging

    # ============================================================
    # STEP 8 — SLA SUMMARY REPORT
    # How many orders met their delivery promise?
    # ← ADD #2 FINAL OUTPUT HERE
    # ============================================================
    total_orders    = len(orders)
    fulfilled       = len(orders[orders['Fulfilled']  == 'Yes'])
    sla_met         = len(orders[orders['SLA_Met']    == 'Yes'])
    unfulfilled     = len(orders[orders['Fulfilled']  == 'No'])

    print("=" * 50)
    print("FULFILLMENT SUMMARY")
    print("=" * 50)
    print(f"Total Orders:        {total_orders}")
    print(f"Fulfilled:           {fulfilled}  ({round(fulfilled/total_orders*100, 1)}%)")
    print(f"SLA Met:             {sla_met}     ({round(sla_met/total_orders*100, 1)}%)")
    print(f"Unfulfilled:         {unfulfilled} ({round(unfulfilled/total_orders*100, 1)}%)")
    print("=" * 50)

    return [orders, centers]