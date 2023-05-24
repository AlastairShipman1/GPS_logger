from datetime import timedelta

import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import os



def process_data(df):
    # get everything into the desired format
    df["DATE"] = df["DATE"].astype(str)
    df["TIME"] = df["TIME"].astype(str)
    df['speed'] = df['SPEED']  # this is pre-computed, seems to align well, but is in km/h

    df['date_length'] = df.DATE.str.len()
    df['time_length'] = df.TIME.str.len()

    # if there is an error with the date_length, or time_length, then we just drop the rows.
    df = df[df.date_length == 6]
    df = df[df.time_length == 6]

    df['timestamp'] = df['DATE'] + df['TIME']
    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%y%m%d%H%M%S')

    # get rid of the trailing N/E values
    df.loc[:, 'LATITUDE N/S'] = df["LATITUDE N/S"].map(lambda x: x[:-1]).astype(float)
    df.loc[:, 'LONGITUDE E/W'] = df["LONGITUDE E/W"].map(lambda x: x[:-1]).astype(float)

    # it is WGS84
    # want to project to EPSG:3857
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["LATITUDE N/S"], df["LONGITUDE E/W"]), crs="EPSG:4326")
    gdf_m = gdf.to_crs("EPSG:3857")

    # get a list of each unique day that this sensor has been running
    # for each day, get the cumulative distance value (above)
    # there are three sets of times: the off time, the active time, the idle time.
    # the off time can be defined as when the time between datapoints is more than 5 st. devs above the mean
    # the idle time can be defined as when a datapoint speed is lower than a preset value (e.g. 0.5 m/s)
    # note that this will still need cleaning, as it is noisy data. see later for this.

    days_to_consider = list(gdf.timestamp.dt.floor('d').dt.day.unique())

    for day in days_to_consider:
        # get the values from this particular day
        temp_df = gdf_m.loc[gdf_m.timestamp.dt.floor('d').dt.day == day].copy()

        # this filters out data points that are more than SIGMAS sigma away from the mean displacement
        # (stops anomalies from messing with the analysis)
        temp_df['distance_from_previous'] = temp_df.distance(temp_df.shift(1))
        displ_mean = temp_df["distance_from_previous"].mean()
        displ_std = temp_df["distance_from_previous"].std()
        temp_df = temp_df.loc[(temp_df["distance_from_previous"] < displ_mean + SIGMAS * displ_std)]

        # this allows us to compute the speeds and the total distance moved
        temp_df['time_from_previous'] = temp_df.timestamp.diff().dt.total_seconds()
        # i think there's a whole bunch of repeated data points?
        temp_df=temp_df.loc[temp_df.time_from_previous>0]
        temp_df['computed_speed'] = temp_df['distance_from_previous'] / temp_df['time_from_previous']  # this is in m/s
        day_distance = temp_df.groupby(temp_df.timestamp.dt.floor('d').dt.day)['distance_from_previous'].cumsum().max()

        # now we need to determine when the vehicle is idle. start by getting mean and std values
        dt_mean = temp_df.time_from_previous.mean()
        dt_std = temp_df.time_from_previous.std()

        # say the car is active when moving faster than IDLE_SPEED AND the time from previous is less than a set value
        temp_df['active'] = 0
        temp_df.loc[temp_df.computed_speed > IDLE_SPEED, 'active'] = 1
        temp_df['active_time'] = temp_df.active * temp_df.time_from_previous

        # say the car is idle when moving slower than IDLE_SPEED AND the time from previous is less than a set value
        temp_df['idle'] = 0
        temp_df.loc[temp_df.computed_speed < IDLE_SPEED, 'idle'] = 1
        temp_df['idle_time'] = temp_df.idle * temp_df.time_from_previous

        # say the car is off when the previous data point is too long in the past
        temp_df['off'] = 0
        temp_df.loc[temp_df.time_from_previous > dt_mean + SIGMAS * dt_std, 'off'] = 1
        temp_df['off_time'] = temp_df.off * temp_df.time_from_previous

        # there are therefore three conditions: active, idle, and off.
        # we need to know when there are continuous idle periods of, say, 20MINS or more
        # # Create a mask to identify idle rows
        mask = temp_df['idle'] == 1

        # Create a new column 'idle_period_window' to calculate the number of consecutive idle rows, with a hacky workaround
        temp_df['idle_period_window'] = mask.groupby((~mask).cumsum()).transform('sum')
        temp_df.loc[temp_df['idle'] == 0, 'idle_period_window'] = 0
        temp_df['idle_period_window'] = temp_df['idle_period_window'].fillna(0)

        temp_df['idle_duration'] = 0

        temp_df.reset_index(inplace=True, drop=True)
        starting_index = 0
        for index, row in temp_df.iterrows():
            # check if idle
            if row['idle'] == 1:
                period = row['idle_period_window']
                post = period + starting_index
                temp_df.loc[index, 'idle_duration'] = (temp_df.loc[post,'timestamp']-temp_df.loc[starting_index,  'timestamp']).total_seconds()
            else:
                starting_index = index

        total_active_time = temp_df.loc[temp_df['active_time'] > 0, 'time_from_previous'].cumsum().max()
        total_idle_time = temp_df.loc[temp_df['idle_time'] > 0, 'time_from_previous'].cumsum().max()

        x = temp_df.loc[temp_df.idle_duration > IDLE_DURATION_THRESHOLD]
        x.reset_index(inplace=True, drop=True)

        y = temp_df.loc[temp_df.idle == 1]

        # uncomment these if you want to start plotting
        # fig, ax = plt.subplots()
        # ax.scatter(temp_df.timestamp, temp_df.computed_speed)
        #
        # ax.scatter(y.timestamp, y.computed_speed)
        # ax.scatter(x.timestamp, x.computed_speed)
        # plt.show()

        # summary values for each day
        print(day)
        print(f'Total distance travelled (km): {day_distance / 1000:.2f}')
        print(f'Total active time (mins): {total_active_time / 60:.2f}')
        # print(f'Total idle time (mins): {total_idle_time / 60:.2f}')
        print(f'Total potential charging time (mins): {x.idle_duration.unique().sum()/60 :.2f}')


IDLE_SPEED = .5  # in m/s
SIGMAS = 15  # standard deviations
IDLE_DURATION_THRESHOLD = 15*60  # in seconds. alternatively: timedelta(seconds=20 * 60)

def main():
    # use this as a short example
    # df = pd.read_csv('./Data/sample_data.csv')
    # process_data(df)
    # return

    for root, dirs, files in os.walk('./Data/'):
        if len(files) > 0:
            if files[0] == "sample_data.csv": continue
            for file in files:
                df = pd.read_csv(os.path.join(root, file), header=0)
                # the files get quite big, so just do it on a file by file basis.
                process_data(df)


if __name__=="__main__":
    main()
