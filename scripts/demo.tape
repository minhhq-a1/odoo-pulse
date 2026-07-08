# Renders assets/business_pulse.gif — requires: brew install vhs; make playground
Output assets/business_pulse.gif
Set FontSize 15
Set Width 1000
Set Height 700
Set Padding 16
Set TypingSpeed 35ms
Hide
Type `export ODOO_URL=http://localhost:8069 ODOO_DB=playground ODOO_USERNAME=admin ODOO_API_KEY=admin ODOO_READ_ONLY=true`
Enter
Type "clear"
Enter
Show
Type `python3 scripts/demo_pulse.py --print   # "how's the company doing today?"`
Sleep 800ms
Enter
Sleep 7s
