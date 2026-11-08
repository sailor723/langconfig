\pset pager off
\echo == COUNTS ==
select 'driver_schedule',count(*) from driver_schedule
union all select 'incident_tickets',count(*) from incident_tickets
union all select 'violations',count(*) from violations
union all select 'fuel_logs',count(*) from fuel_logs
union all select 'maintenance_orders',count(*) from maintenance_orders
union all select 'zone_permits',count(*) from zone_permits
union all select 'vehicle_fixed_costs',count(*) from vehicle_fixed_costs
union all select 'restriction_calendar',count(*) from restriction_calendar
union all select 'vehicle_axles',count(*) from vehicle_axles
union all select 'trips',count(*) from trips
union all select 'stops',count(*) from stops
union all select 'vehicles',count(*) from vehicles;

\echo == driver_schedule status/scheduled ==
select status, scheduled, count(*), count(hours) hh, count(reason) rr from driver_schedule group by 1,2 order by 1,2;

\echo == incident_tickets ==
select type, is_primary, count(*) from incident_tickets group by 1,2 order by 3 desc;
select channel, count(*) from incident_tickets group by 1 order by 2 desc;
select responsible_party, count(*) from incident_tickets group by 1 order by 2 desc;
select status, count(*) from incident_tickets group by 1 order by 2 desc;
select count(*), count(stop_id) from incident_tickets;

\echo == violations ==
select category, count(*), sum(points), sum(fine_amount) from violations group by 1 order by 2 desc;
select status, count(*) from violations group by 1;
select road_zone, count(*) from violations group by 1;
select count(distinct vehicle_id), count(distinct driver_id) from violations;

\echo == fuel_logs ==
select count(*), min(filled_at)::date, max(filled_at)::date, sum(liters), sum(amount), round(avg(unit_price),4) from fuel_logs;
select count(distinct vehicle_id) from fuel_logs;
select station, count(*) from fuel_logs group by 1 order by 2 desc limit 10;

\echo == maintenance_orders ==
select count(*), count(closed_at), sum(cost), round(avg(cost),2), sum(downtime_hours), min(opened_at), max(opened_at) from maintenance_orders;
select category, count(*), round(sum(cost),2) from maintenance_orders group by 1 order by 3 desc;
select vendor, count(*) from maintenance_orders group by 1 order by 2 desc limit 10;

\echo == zone_permits ==
select status, count(*), count(distinct vehicle_id) from zone_permits group by 1;
select zone, count(*) from zone_permits group by 1;
select count(distinct vehicle_id) from zone_permits;

\echo == vehicle_fixed_costs ==
select count(*), count(distinct vehicle_id), min(period), max(period), round(sum(insurance+depreciation+road_tax+inspection),2) from vehicle_fixed_costs;
select currency, count(*) from vehicle_fixed_costs group by 1;
select count(distinct period) from vehicle_fixed_costs;

\echo == restriction_calendar ==
select zone, restricted, count(*) from restriction_calendar group by 1,2 order by 1,2;
select restriction_type, count(*) from restriction_calendar group by 1;

\echo == vehicle_axles ==
select axle_type, count(*), round(avg(rated_kg),1) from vehicle_axles group by 1;
select count(distinct vehicle_id), min(n), max(n) from (select vehicle_id, count(*) n from vehicle_axles group by 1) s;
select count(*) from (select vehicle_id from vehicle_axles group by 1 having abs(sum(load_share)-1)>0.001) s;

\echo == trips new columns ==
select count(*), count(actual_km), round(sum(actual_km),1), round(avg(actual_km),2) from trips;
select count(*), count(fuel_liters), round(sum(fuel_liters),1), round(sum(cost_total+maintenance_cost+fixed_cost),2) from trips;
select count(*) filter (where axle_overload) axle_ov, count(*) filter (where core_restricted) core_r, count(*) filter (where core_restricted and not permit_valid) core_no_permit, count(*) filter (where stops_delivered>=planned_stops) completed, count(*) from trips;
select route_version, count(*), round(avg(actual_km),1) from trips group by 1;
select min(trip_date), max(trip_date) from trips;

\echo == stops service_status ==
select service_status, count(*) from stops group by 1 order by 2 desc;
select count(*), count(*) filter (where on_time) ontime, count(*) filter (where temp_excursion) temp, sum(damaged_boxes), sum(baskets_missing), count(*) filter (where alarm_triggered) alarm from stops;
select count(distinct trip_id) from stops where temp_excursion or damaged_boxes>0;
select count(*) filter (where late_stop_count>0) trips_with_late, count(*) from trips;

\echo == K2 candidates ==
select count(*) from trips t where exists (select 1 from stops s where s.trip_id=t.id and (s.temp_excursion or s.damaged_boxes>0));
select count(*) from (select distinct trip_id from incident_tickets) s;
select count(*) from (select distinct t.id from trips t where exists(select 1 from stops s where s.trip_id=t.id and (s.temp_excursion or s.damaged_boxes>0)) union select distinct trip_id from incident_tickets) s;
select count(*) from (select distinct t.id from trips t where exists(select 1 from stops s where s.trip_id=t.id and (s.temp_excursion or s.damaged_boxes>0)) union select distinct trip_id from incident_tickets union select distinct s.trip_id from complaints c join stops s on s.id=c.stop_id) s;
