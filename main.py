import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import os

# for file, path in os.walk('./Data/'):


df1 = pd.read_csv("./Data/GPS Logger 1/2023-05/12000000.CSV", header=0)
df2 =  pd.read_csv("./Data/GPS Logger 1/2023-05/12102203.CSV", header=0)
df3 =pd.read_csv("./Data/GPS Logger 1/2023-05/13000000.CSV", header=0)

df = pd.concat([df1, df2, df3], axis=0)
df.reset_index(inplace=True)
print(df.columns)
df["DATE"] = df["DATE"].astype(str)
df["TIME"] = df["TIME"].astype(str)
df['speed'] = df['SPEED']  # this is pre-computed, seems to align well, but is in km/h

df['date_length'] = df.DATE.str.len()
df['time_length'] = df.TIME.str.len()

# if there is an error with the date_length, or time_length, then we just drop the rows.
df = df[df.date_length == 6]
df = df[df.time_length == 6]

df['timestamp'] = df['DATE'] + df['TIME']
df['timestamp'] = pd.to_datetime(df['timestamp'], format='%d%m%y%H%M%S')

df.loc[:, 'LATITUDE N/S'] = df["LATITUDE N/S"].map(lambda x: x[:-1]).astype(float)
df.loc[:, 'LONGITUDE E/W'] = df["LONGITUDE E/W"].map(lambda x: x[:-1]).astype(float)

# it is WGS84
# want to project to EPSG:3857
gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["LATITUDE N/S"], df["LONGITUDE E/W"]), crs="EPSG:4326")
gdf_m = gdf.to_crs("EPSG:3857")

# get a list of each unique day that this sensor has been running
# for each day, get the cumulative distance value (above)
# there are three sets of times: the off time, the active time, the idle time.
# the off time can be defined as when the time between datapoints is more than 3 st. devs above the mean
# the idle time can be defined as when a datapoint speed is lower than a preset value (e.g. 0.1 m/s)
IDLE_SPEED = 0.1
SIGMAS = 3
days_to_consider = list(gdf.timestamp.dt.floor('d').dt.day.unique())
for day in days_to_consider:
    temp_df = gdf_m.loc[gdf_m.timestamp.dt.floor('d').dt.day == day].copy()
    temp_df['distance_from_previous'] = temp_df.distance(temp_df.shift(1))
    temp_df['time_from_previous'] = temp_df.timestamp.diff().dt.total_seconds()
    temp_df['computed_speed'] = temp_df['distance_from_previous'] / temp_df['time_from_previous']  # this is in m/s
    day_distance = temp_df.groupby(temp_df.timestamp.dt.floor('d').dt.day)['distance_from_previous'].cumsum().max()

    dt_mean = temp_df.time_from_previous.mean()
    dt_std = temp_df.time_from_previous.std()

    temp_df['active_time'] = temp_df.loc[(temp_df.time_from_previous < dt_mean + SIGMAS * dt_std) & (
                temp_df.computed_speed > IDLE_SPEED)].time_from_previous
    temp_df['idle_time'] = temp_df.loc[(temp_df.time_from_previous < dt_mean + SIGMAS * dt_std) & (
                temp_df.computed_speed < IDLE_SPEED)].time_from_previous

    total_active_time = temp_df.loc[temp_df['active_time'] > 0, 'time_from_previous'].cumsum().max()
    total_idle_time = temp_df.loc[temp_df['idle_time'] > 0, 'time_from_previous'].cumsum().max()

    # uncomment these if you want to start plotting
    # x = temp_df.loc[temp_df.idle_time > 0]
    # plt.scatter(temp_df.timestamp, temp_df.speed)
    # plt.scatter(x.timestamp, x.speed)
    # plt.show()

    # TODO: put in longest idle sections. figure out how much charging time you have on average.

    # summary values for each day
    print(day)
    print(f'Total distance travelled (km): {day_distance / 1000:.2f}')
    print(f'Total active time (s): {total_active_time:.2f}')
    print(f'Total idle time (s): {total_idle_time:.2f}')

#
