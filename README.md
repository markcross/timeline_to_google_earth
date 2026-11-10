Since Google moved Timeline onto the phone in 2024, the Settings.json you get from Google Takeout often holds only your Timeline settings and no location points. Or Google appear to have vaporised it

If it does, export from the phone instead: on Android go to Settings → Location → Location services → Timeline → Export Timeline data, which gives you Timeline.json.

On iPhone, open Google Maps, then Your Timeline → ⋮ → Location & privacy settings → Export Timeline data.

NB. When moving phones Backup to Google your Timeline on your phone (logged into Google), then on the new phone when logged into Google - Import

$ python3 timeline_to_google_earth.py 
usage: timeline_to_google_earth.py [-h] [-s YYYY-MM-DD] [-e YYYY-MM-DD] [-a] [-i FILE] [-o FILE]
                                   [-show ITEM [ITEM ...]]

Convert a Google Timeline export (JSON) into a Google Earth KML file for a given date range.

options:
  -h, --help            show this help message and exit
  -s YYYY-MM-DD, --start YYYY-MM-DD
                        start date (inclusive). If omitted, starts from the first record
  -e YYYY-MM-DD, --end YYYY-MM-DD
                        end date (inclusive). If omitted, runs to the last record
  -a, --all             export every record in the file (same as no -s and no -e)
  -i FILE, --input FILE
                        Timeline JSON file (default: first of Settings.json, Timeline.json, location-history.json,
                        Records.json found)
  -o FILE, --output FILE
                        output KML file (default: timeline_START_to_END.kml)
  -show ITEM [ITEM ...], --show ITEM [ITEM ...]
                        what to include: any of pins, routes, labels, all_details (default: pins). See 'what to show'
                        below

examples:
  timeline_to_google_earth.py -s 2024-06-01 -e 2024-06-30
      Export June 2024 (both dates inclusive).

  timeline_to_google_earth.py -s 2024-06-01
      Export from 1 June 2024 to the last record in the file.

  timeline_to_google_earth.py -e 2024-06-30
      Export from the first record in the file up to 30 June 2024.

  timeline_to_google_earth.py -a
      Export everything in the file.

  timeline_to_google_earth.py -s 2024-06-01 -e 2024-06-07 -i Timeline.json -o week.kml
      Choose the input file and output file names.

what to show (-show), default is pins only:
  -show pins                   place pins only (same as the default)
  -show routes                 route lines only
  -show pins routes            pins and route lines
  -show pins labels            pins with time/place text labels
  -show all_details            pins, labels and route lines (the lot)
  Items can also be comma-separated, e.g. -show pins,routes
  Without labels, click a pin in Google Earth to see its time and place.

notes:
  If -i is not given, the script looks in the current directory for:
  Settings.json, Timeline.json, location-history.json, Records.json (first found).
  Open the resulting .kml in Google Earth (File > Open / Import KML).
