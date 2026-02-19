# FM Radio – Desktop Internet Radio

A desktop FM-style radio player for Windows (and other desktops) that plays internet radio streams with a vintage look.

![Python](https://img.shields.io/badge/python-3.8+-blue)  
Requires **VLC media player** to be installed for playback.

## Features

- **FM-style interface** – Frequency display, volume
- **Station list** – Browse and select from built-in internet stations
- **Prev/Next** – Step through stations
- **Play/Pause** and **Stop**
- **Volume** slider

## Setup

1. **Install VLC**  
   Download and install from: https://www.videolan.org/vlc/

2. **Create a virtual environment (optional but recommended)**

   ```bash
   cd desktop-radio
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Install Python dependency**

   ```bash
   pip install -r requirements.txt
   ```

## Run

```bash
python fm_radio.py
```

## Stations

Stations are defined in `stations.json`. You can add or edit entries:

```json
{
  "stations": [
    {
      "name": "My Station",
      "url": "https://example.com/stream.mp3",
      "frequency": "98.5"
    }
  ]
}
```

- **name** – Label shown in the app  
- **url** – Stream URL (MP3, AAC, etc.; VLC handles most formats)  
- **frequency** – Display only (e.g. "98.5" for 98.5 MHz)

## Troubleshooting

- **“Could not start VLC”** – Install VLC and ensure it runs on your system. On some setups you may need to set the `VLC_PLUGIN_PATH` or install VLC in a standard location.
- **No sound** – Check system volume and the app’s volume slider; try another station.
- **Stream won’t play** – The stream URL may be down or restricted; try a different station or URL.

## License

Use and modify freely.

