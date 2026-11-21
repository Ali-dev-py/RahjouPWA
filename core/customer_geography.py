"""Batch customer geography labels; options only come from visible customers."""
from .income_report import guid


def customer_geography(customers, province_rows, city_rows):
    provinces = {guid(p['id']): p['name'] for p in province_rows}
    cities = {guid(c['id']): c['name'] for c in city_rows}
    province_options, city_options = {}, {}
    for customer in customers:
        customer.province_key = guid(getattr(customer, 'gprovinceid', None)) or 'none'
        customer.city_key = guid(getattr(customer, 'gcityid', None)) or 'none'
        customer.province_name = provinces.get(customer.province_key) or 'استان نامشخص'
        customer.city_name = cities.get(customer.city_key) or 'شهر نامشخص'
        province_options[customer.province_key] = customer.province_name
        city_options[(customer.city_key, customer.province_key)] = customer.city_name
    return (
        sorted([{'id': key, 'name': name} for key, name in province_options.items()], key=lambda item: item['name']),
        sorted([{'id': key, 'province': province, 'name': name} for (key, province), name in city_options.items()], key=lambda item: item['name']),
    )
