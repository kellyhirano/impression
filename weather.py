#!/usr/bin/env python3

import configparser
import json
import re
import time
import traceback
import urllib.request

import paho.mqtt.client as mqtt
from PIL import Image, ImageFont, ImageDraw
from inky.inky_uc8159 import Inky

# Global data store
g_mqtt_data = {}
g_awair_mqtt_rooms = ()
g_awair_mqtt_ext_rooms = ()
g_heartbeat_url = None
g_mqtt_connected = False
g_recent_disconnect = False
g_temp_history = []   # (unix_time, outdoor_temp_F) from weewx/sensor
g_power_history = []  # (unix_time, kW) from rainforest/load, 1/min
g_pool_temp_history = []  # (unix_time, pool_temp_F) from pool/sensor

# Display layout constants (600x448)
LEFT_PANEL_WIDTH = 185    # outdoor conditions: x=0 to 184
RIGHT_PANEL_X = 185       # awair rooms start here
DIVIDER_Y = 310           # splits indoor section from forecast
FORECAST_GAP = 8          # px between divider line and first forecast item
MAX_FORECAST_ITEMS = 6

# Temperature trend chart (left panel, below outdoor conditions)
CHART_X = 7
CHART_Y = 218
CHART_W = 133
CHART_H = 84
CHART_LABEL_H = 14        # px reserved at bottom for day labels
CHART_BAR_H = CHART_H - CHART_LABEL_H  # 70px for bars
CHART_BAR_W = 12

# Sparkline graph constants (right side, below indoor content)
GRAPH_X = 195
GRAPH_W = 398
GRAPH_H = 38
GRAPH_Y = 258             # both sparklines share this top y
GRAPH_GAP = 6
GRAPH_LABEL_PAD = 4
HISTORY_SECONDS = 3 * 3600  # 3 hours of data


def on_connect(client, userdata, flags, rc):
    global g_mqtt_connected
    if rc == 0:
        print("Connected to MQTT broker")
        g_mqtt_connected = True
        subs = [("weathergov/forecast", 0), ("weathergov/warnings", 0),
                ("weathergov/temptrend", 0),
                ("weewx/sensor", 0), ("purpleair/sensor", 0),
                ("rainforest/load", 0), ("pool/sensor", 0)]
        for room in g_awair_mqtt_rooms:
            subs.append(("awair/" + room + "/sensor", 0))
        client.subscribe(subs)
    else:
        print(f"Connection failed with code {rc}")
        g_mqtt_connected = False


def on_disconnect(client, userdata, rc):
    global g_mqtt_connected, g_recent_disconnect
    g_mqtt_connected = False
    g_recent_disconnect = True
    if rc != 0:
        print(f"Unexpected MQTT disconnection (rc={rc}). Will auto-reconnect...")
    else:
        print("Disconnected from MQTT broker")


def on_message(client, userdata, msg):
    global g_mqtt_data
    try:
        data = json.loads(msg.payload.decode('UTF-8'))
        g_mqtt_data[msg.topic] = data
        print("MESSAGE: " + msg.topic)

        now = time.time()
        if msg.topic == 'weewx/sensor':
            temp = data.get('outdoor_temperature')
            if temp is not None:
                g_temp_history.append((now, float(temp)))
                cutoff = now - HISTORY_SECONDS
                g_temp_history[:] = [(t, v) for t, v in g_temp_history
                                     if t >= cutoff]
        elif msg.topic == 'pool/sensor':
            pool_temp = data.get('pool_temp')
            if pool_temp is not None:
                g_pool_temp_history.append((now, float(pool_temp)))
                cutoff = now - HISTORY_SECONDS
                g_pool_temp_history[:] = [(t, v) for t, v in g_pool_temp_history
                                           if t >= cutoff]
        elif msg.topic == 'rainforest/load':
            kw = data.get('instantaneous')
            if kw is not None:
                if not g_power_history or now - g_power_history[-1][0] >= 60:
                    g_power_history.append((now, float(kw)))
                    cutoff = now - HISTORY_SECONDS
                    g_power_history[:] = [(t, v) for t, v in g_power_history
                                          if t >= cutoff]
    except json.JSONDecodeError as e:
        print(f"Failed to parse MQTT message on {msg.topic}: {e}")
    except Exception as e:
        print(f"Error processing MQTT message: {e}")


def co2_color(co2):
    """Color-code CO2 level: normal=BLACK, moderate=ORANGE, high=RED."""
    co2_int = int(co2)
    if co2_int > 1000:
        return inky_display.RED
    if co2_int > 600:
        return inky_display.ORANGE
    return inky_display.BLACK


def draw_outdoor_section(draw, giant_font, large_font, small_font, x, y):
    """Left panel: outdoor temp, deltas, AQI, wind, rain."""
    weewx = g_mqtt_data.get('weewx/sensor', {})
    temp = weewx.get('outdoor_temperature', 0)
    temp_delta = weewx.get('outdoor_temp_change', 0)
    temp_24h_delta = weewx.get('outdoor_24h_temp_change', 0)

    # Outdoor temp — shrink font if triple digits
    temp_font = large_font if temp >= 100 else giant_font
    delta_x_offset = -60 if temp >= 100 else 0
    delta_y_offset = 20 if temp >= 100 else 0

    draw.text((x, y), '{}\u00b0'.format(int(temp)),
              inky_display.BLACK, font=temp_font)
    draw.text((x + 120 + delta_x_offset, y + delta_y_offset + 49),
              '{:+.1f}\u00b0'.format(float(temp_delta)),
              inky_display.BLACK, font=small_font)
    draw.text((x + 120, y + 69),
              '{:+.1f}\u00b0'.format(float(temp_24h_delta)),
              inky_display.BLACK, font=small_font)

    purpleair = g_mqtt_data.get('purpleair/sensor', {})
    aqi = purpleair.get('st_aqi', 0)
    lrapa_aqi = purpleair.get('st_lrapa_aqi', 0)
    last_hour_aqi = purpleair.get('st_aqi_last_hour', 0)
    last_hour_lrapa = purpleair.get('st_lrapa_aqi_last_hour', 0)
    aqi_desc = purpleair.get('st_aqi_desc', '')
    wind_gust = weewx.get('wind_gust', 0)
    last_day_rain = weewx.get('last_day_rain', 0)
    rain_rate = weewx.get('rain_rate', 0)

    cy = y + 96
    draw.text((x, cy),
              'A{} {:+d}  L{} {:+d}'.format(aqi, last_hour_aqi,
                                             lrapa_aqi, last_hour_lrapa),
              inky_display.BLACK, font=small_font)
    cy += 22

    if aqi > 100:
        draw.text((x, cy), aqi_desc, inky_display.RED, font=small_font)
        cy += 22

    if wind_gust >= 10:
        draw.text((x, cy), 'GUST: {}'.format(wind_gust),
                  inky_display.BLACK, font=small_font)
        cy += 22

    if last_day_rain > 0:
        rain_str = '24h: {}"'.format(last_day_rain)
        if rain_rate > 0:
            rain_str += ' @{:.2f}"/h'.format(rain_rate)
        draw.text((x, cy), rain_str, inky_display.BLACK, font=small_font)
        cy += 22

    rainforest = g_mqtt_data.get('rainforest/load', {})
    power_kw = rainforest.get('instantaneous')
    if power_kw is not None:
        draw.text((x, cy), '{:.2f}kW'.format(float(power_kw)),
                  inky_display.BLACK, font=small_font)
        cy += 22

    pool = g_mqtt_data.get('pool/sensor', {})
    pool_temp = pool.get('pool_temp')
    if pool_temp is not None:
        draw.text((x, cy), 'Pool: {:.0f}\u00b0'.format(pool_temp),
                  inky_display.BLACK, font=small_font)
        cy += 22
        draw.text((x, cy), 'Pu:{} PH:{}'.format(
                  pool.get('pool_pump', '?'), pool.get('pool_heater', '?')),
                  inky_display.BLACK, font=small_font)
        cy += 22
        draw.text((x, cy), 'SH:{} Lt:{}'.format(
                  pool.get('spa_heater', '?'), pool.get('pool_light', '?')),
                  inky_display.BLACK, font=small_font)


def draw_awair_line(draw, font, x, y, topic_substr):
    """One Awair room: initial  temp  delta  CO2(color)  humidity  voc."""
    topic = 'awair/' + topic_substr + '/sensor'
    if topic not in g_mqtt_data:
        return
    data = g_mqtt_data[topic]
    temp = data.get('temp', 0)
    co2 = data.get('co2', 0)
    humid = data.get('humid', 0)
    voc = data.get('voc', 0)
    temp_change = data.get('last_hour_temp', 0)
    aqi = data.get('aqi', 0)

    room_label = topic_substr.split('/')[-1][0]
    draw.text((x, y), room_label, inky_display.BLACK, font=font)
    draw.text((x + 22, y), '{}\u00b0'.format(temp),
              inky_display.BLACK, font=font)
    draw.text((x + 82, y), '{:+.1f}\u00b0'.format(float(temp_change)),
              inky_display.BLACK, font=font)
    if aqi > 100:
        draw.text((x + 152, y), 'A{}'.format(int(aqi)),
                  inky_display.RED, font=font)
    else:
        draw.text((x + 152, y), str(int(co2)),
                  co2_color(co2), font=font)
    draw.text((x + 215, y), '{}%'.format(int(float(humid))),
              inky_display.BLACK, font=font)
    draw.text((x + 290, y), '{}v'.format(int(voc)),
              inky_display.BLACK, font=font)


def draw_kitchen_line(draw, font, x, y):
    """Kitchen temp from weewx indoor sensor + current time."""
    weewx = g_mqtt_data.get('weewx/sensor', {})
    indoor_temp = weewx.get('indoor_temperature', 0)
    indoor_temp_change = weewx.get('indoor_temp_change', 0)
    draw.text((x, y), 'K', inky_display.BLACK, font=font)
    draw.text((x + 22, y), '{:.1f}\u00b0'.format(float(indoor_temp)),
              inky_display.BLACK, font=font)
    draw.text((x + 82, y), '{:+.1f}\u00b0'.format(float(indoor_temp_change)),
              inky_display.BLACK, font=font)
    draw.text((x + 160, y), time.strftime("%H:%M", time.localtime()),
              inky_display.BLACK, font=font)


def draw_ext_awair_line(draw, font, x, y):
    """External Awair rooms: initial + temp (no room count limit)."""
    for ext_room in g_awair_mqtt_ext_rooms:
        topic = 'awair/' + ext_room + '/sensor'
        if topic not in g_mqtt_data:
            continue
        data = g_mqtt_data[topic]
        label = ext_room.split('/')[-1][0]
        aqi = data.get('aqi', 0)
        draw.text((x, y), label, inky_display.BLACK, font=font)
        if aqi > 100:
            draw.text((x + 22, y), 'A{}'.format(int(aqi)),
                      inky_display.RED, font=font)
        else:
            draw.text((x + 22, y), '{}\u00b0'.format(data.get('temp', 0)),
                      inky_display.BLACK, font=font)
        x += 85


def draw_forecast(draw, font, start_y):
    """Forecast + weather warnings in bottom section."""
    line_h = font.getbbox('Ay')[3] + 2
    count = 1

    for warning in g_mqtt_data.get('weathergov/warnings', []):
        day_str = '{}: {}'.format(warning.get('title', '').title(),
                                  warning.get('desc', ''))
        draw.text((7, start_y + count * line_h),
                  day_str, inky_display.RED, font=font)
        count += 1
        if count > MAX_FORECAST_ITEMS:
            return

    for day_info in g_mqtt_data.get('weathergov/forecast', []):
        time_str = day_info.get('day', '')
        time_str = re.sub('BIRTHDAY', 'BDAY', time_str)
        time_str = re.sub(r'(\S{3})\S*DAY', r'\1', time_str)
        time_str = re.sub(r'THIS ', '', time_str)
        day_str = '{}: {}, {}\u00b0'.format(
            time_str, day_info.get('forecast', ''), day_info.get('temp', ''))
        precip = day_info.get('precip_amount')
        if precip:
            day_str += ' {}'.format(precip)
        draw.text((7, start_y + count * line_h),
                  day_str, inky_display.BLACK, font=font)
        count += 1
        if count > MAX_FORECAST_ITEMS:
            break


def draw_temp_chart(draw, font):
    """7-day temperature bar chart in the left panel (CHART_X/Y/W/H)."""
    data = g_mqtt_data.get('weathergov/temptrend', {})
    days = data.get('days', [])
    if not days:
        return

    # Collect all values to set Y-scale
    all_temps = []
    for d in days:
        for key in ('actual_high', 'actual_low', 'forecast_high', 'forecast_low',
                    'normal_high', 'normal_low', 'record_high', 'record_low'):
            v = d.get(key)
            if v is not None:
                all_temps.append(float(v))
    if not all_temps:
        return

    y_min = (int(min(all_temps)) // 10) * 10
    y_max = ((int(max(all_temps)) + 9) // 10) * 10
    if y_max <= y_min:
        y_max = y_min + 10
    temp_range = y_max - y_min

    def temp_to_y(temp):
        # Higher temp → smaller y (closer to top of chart)
        return (CHART_Y + CHART_BAR_H - 1
                - int((float(temp) - y_min) / temp_range * (CHART_BAR_H - 1)))

    slot_w = CHART_W // 7  # 19px

    for i, day in enumerate(days[:7]):
        slot_x = CHART_X + i * slot_w
        bar_x  = slot_x + (slot_w - CHART_BAR_W) // 2

        actual_high   = day.get('actual_high')
        actual_low    = day.get('actual_low')
        forecast_high = day.get('forecast_high')
        forecast_low  = day.get('forecast_low')

        # Determine bar temps and color
        if actual_high is not None and actual_low is not None:
            bar_high  = actual_high
            bar_low   = actual_low
            bar_color = inky_display.BLUE if i == 3 else inky_display.ORANGE
        elif forecast_high is not None:
            bar_high  = forecast_high
            bar_low   = forecast_low if forecast_low is not None else forecast_high
            bar_color = inky_display.GREEN
        else:
            bar_high = bar_low = None

        if bar_high is not None:
            y_top = temp_to_y(bar_high)
            y_bot = temp_to_y(bar_low)
            if y_top > y_bot:
                y_top, y_bot = y_bot, y_top
            # Ensure at least 2px tall so a flat bar is visible
            if y_bot == y_top:
                y_bot = y_top + 2
            draw.rectangle([(bar_x, y_top), (bar_x + CHART_BAR_W - 1, y_bot)],
                           fill=bar_color)

        # Normal range tick marks and record lines share the same x-span
        tick_x1 = bar_x - 1
        tick_x2 = bar_x + CHART_BAR_W
        for key in ('normal_high', 'normal_low'):
            v = day.get(key)
            if v is not None:
                ny = temp_to_y(v)
                if CHART_Y <= ny <= CHART_Y + CHART_BAR_H - 1:
                    draw.line([(tick_x1, ny), (tick_x2, ny)],
                              fill=inky_display.BLACK, width=1)

        # Record high/low lines (same width as normal ticks, RED)
        for key in ('record_high', 'record_low'):
            v = day.get(key)
            if v is not None:
                ry = temp_to_y(v)
                if CHART_Y <= ry <= CHART_Y + CHART_BAR_H - 1:
                    draw.line([(tick_x1, ry), (tick_x2, ry)],
                              fill=inky_display.RED, width=1)

        # Day label centered at bottom
        label = day.get('label', '')
        lw = font.getbbox(label)[2]
        lx = slot_x + (slot_w - lw) // 2
        ly = CHART_Y + CHART_BAR_H + 1
        draw.text((lx, ly), label, inky_display.BLACK, font=font)

    # Y-axis labels every 20°F, drawn to the right of the chart
    label_x = CHART_X + CHART_W + 2
    tick = (y_min // 20 + 1) * 20
    while tick <= y_max:
        ly = temp_to_y(tick)
        if CHART_Y <= ly <= CHART_Y + CHART_BAR_H - 1:
            draw.text((label_x, ly - font.getbbox('0')[3] // 2),
                      '{}°'.format(tick), inky_display.BLACK, font=font)
        tick += 20


def draw_sparkline(draw, history, x, y, w, h, color):
    """Draw a line graph of (unix_time, value) history."""
    if len(history) < 2:
        return
    now = time.time()
    t_start = now - HISTORY_SECONDS
    v_min = min(v for _, v in history)
    v_max = max(v for _, v in history)
    if v_max <= v_min:
        v_max = v_min + 1
    points = []
    for t, v in history:
        px = x + int((t - t_start) / HISTORY_SECONDS * (w - 1))
        py = y + h - 1 - int((v - v_min) / (v_max - v_min) * (h - 1))
        points.append((max(x, min(x + w - 1, px)),
                       max(y, min(y + h - 1, py))))
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=color, width=2)


def draw_graphs(draw, label_font, value_font):
    """Pool temp (red), outdoor temp (blue), power (green) sparklines."""
    del label_font

    slot_w = (GRAPH_W - 2 * GRAPH_GAP) // 3
    val_h = value_font.getbbox('0')[3]

    pool_x = GRAPH_X
    temp_x = GRAPH_X + slot_w + GRAPH_GAP
    power_x = GRAPH_X + 2 * (slot_w + GRAPH_GAP)

    def draw_slot(history, x, color, fmt):
        if len(history) < 2:
            return
        lo = min(v for _, v in history)
        hi = max(v for _, v in history)
        hi_str = fmt.format(hi)
        lo_str = fmt.format(lo)
        label_w = max(value_font.getbbox(hi_str)[2],
                      value_font.getbbox(lo_str)[2])
        graph_w = slot_w - label_w - GRAPH_LABEL_PAD
        draw_sparkline(draw, history, x, GRAPH_Y, graph_w, GRAPH_H, color)
        lx = x + graph_w + GRAPH_LABEL_PAD
        draw.text((lx, GRAPH_Y), hi_str, color, font=value_font)
        draw.text((lx, GRAPH_Y + GRAPH_H - val_h), lo_str, color, font=value_font)

    draw_slot(g_pool_temp_history, pool_x,  inky_display.RED,   '{:.0f}\u00b0')
    draw_slot(g_temp_history,      temp_x,  inky_display.BLUE,  '{:.0f}\u00b0')
    draw_slot(g_power_history,     power_x, inky_display.GREEN, '{:.1f}kW')


def paint_image():
    global g_recent_disconnect

    img = Image.new("P", (inky_display.WIDTH, inky_display.HEIGHT))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (inky_display.WIDTH - 1, inky_display.HEIGHT - 1)],
                   fill=inky_display.WHITE)

    giant_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 96)
    large_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 72)
    regular_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 22)
    small_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 20)
    tiny_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 13)

    # Left: outdoor conditions
    draw_outdoor_section(draw, giant_font, large_font, small_font, 7, 0)

    # Right: Awair rooms (initial, temp, delta, CO2, humidity)
    line_h = 26  # 22pt + 4px gap
    for i, room in enumerate(g_awair_mqtt_rooms):
        draw_awair_line(draw, regular_font,
                        RIGHT_PANEL_X, 7 + i * line_h, room)

    room_count = len(g_awair_mqtt_rooms)
    kitchen_y = 7 + room_count * line_h
    draw_kitchen_line(draw, regular_font, RIGHT_PANEL_X, kitchen_y)

    # Temperature trend chart (left panel)
    draw_temp_chart(draw, tiny_font)

    # Sparkline graphs (right panel, shares y-space with chart)
    draw_graphs(draw, small_font, tiny_font)

    # Divider
    draw.line([(0, DIVIDER_Y), (inky_display.WIDTH - 1, DIVIDER_Y)],
              fill=inky_display.BLACK, width=2)

    # Bottom: forecast (6 items)
    forecast_line_h = small_font.getbbox('Ay')[3] + 2
    draw_forecast(draw, small_font, DIVIDER_Y - forecast_line_h + FORECAST_GAP)

    # DC badge: small red indicator if we've had a recent disconnect
    if g_recent_disconnect:
        dc_font = ImageFont.truetype("freefont/FreeSansBold.ttf", 16)
        draw.text((inky_display.WIDTH - 28, 2), "DC",
                  inky_display.RED, font=dc_font)
        g_recent_disconnect = False

    inky_display.set_image(img)
    inky_display.show()


# --- Startup ---

config = configparser.ConfigParser()
config.read('impression.conf')

mqtt_host = config.get('ALL', 'mqtt_host')
mqtt_host_port = int(config.get('ALL', 'mqtt_host_port'))
g_awair_mqtt_rooms = json.loads(config.get('AWAIR', 'mqtt_subs'))
g_awair_mqtt_ext_rooms = json.loads(config.get('AWAIR', 'mqtt_ext_subs'))
g_heartbeat_url = config.get('ALL', 'heartbeat_url', fallback=None) or None

client = mqtt.Client()
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.connect_async(mqtt_host, mqtt_host_port, 60)
client.loop_start()

inky_display = Inky()

time.tzset()
last_update_time = 0
last_heartbeat_time = 0

while True:
    time.sleep(10)

    if not g_mqtt_connected:
        print('MQTT disconnected, waiting for reconnection...')
        continue

    current_time = int(time.time())

    if g_heartbeat_url and current_time - last_heartbeat_time >= 600:
        try:
            urllib.request.urlopen(g_heartbeat_url, timeout=5)
            last_heartbeat_time = current_time
        except Exception:
            pass

    current_hour = int(time.strftime("%H", time.localtime()))
    current_minute = int(time.strftime("%M", time.localtime()))
    current_total_minutes = current_hour * 60 + current_minute

    if (current_total_minutes >= 6 * 60 + 30 and
            current_total_minutes < 22 * 60 + 30 and
            current_minute % 15 == 0 and
            current_time - last_update_time > 60):
        if 'weewx/sensor' not in g_mqtt_data:
            print('Waiting for weewx/sensor data...')
            continue
        print('Updating display...')
        try:
            paint_image()
            last_update_time = current_time
        except Exception as e:
            print(f'Error updating display: {e}')
            traceback.print_exc()
            last_update_time = current_time
