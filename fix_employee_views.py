import xml.etree.ElementTree as ET

tree = ET.parse('/home/hajril/odoo-dev/academic-19/campus_employees/views/hr_employee_views.xml')
# verify we can parse it
print("Parsed XML successfully.")
