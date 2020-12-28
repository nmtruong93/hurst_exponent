from strategies import *
import backtrader as bt
from datetime import datetime
import os
import pandas as pd
from hurst.pair_stocks import *
from hurst.hurst_calculation import *
from config.config import *
import sys

SPREAD_LOWER_LIMIT = 1
SPREAD_UPPER_LIMIT = 6

def calculateAverageSharpeRatio(ratios, pair, average_sharpe_by_asset, hurst_table, hurst_val):
    if len(ratios) > 0:
        avg_sharpe = sum(ratios) / len(ratios)
        print(pair + " has average sharpe " + str(avg_sharpe))
        average_sharpe_by_asset[pair] = avg_sharpe
        hurst_table[pair] = hurst_val

def runBacktest(limit, file1, file2, ratios):
    symbol1 = file1.split('_')[1]
    symbol2 = file2.split('_')[1]
    cerebro = bt.Cerebro()

    data1 = bt.feeds.YahooFinanceCSVData(
        dataname='../data/' + file1,
        fromdate=datetime.strptime(TEST_START_DATE, '%Y-%M-%d'),
        todate=datetime.strptime(TEST_END_DATE, '%Y-%M-%d'),
    )

    data2 = bt.feeds.YahooFinanceCSVData(
        dataname='../data/' + file2,
        fromdate=datetime.strptime(TEST_START_DATE, '%Y-%M-%d'),
        todate=datetime.strptime(TEST_END_DATE, '%Y-%M-%d'),
    )

    cerebro.adddata(data1)
    cerebro.adddata(data2)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe_ratio')
    cerebro.addsizer(bt.sizers.SizerFix, stake=3)
    start_portfolio_value = cerebro.broker.getvalue()

    cerebro.addstrategy(PairTradingStrategy, upper=limit, lower=-limit)
    run = cerebro.run()
    sharpe = run[0].analyzers.sharpe_ratio.ratio

    if sharpe and sharpe > SHARPE_LOWER_LIMIT and sharpe < SHARPE_UPPER_LIMIT:
        ratios.append(sharpe)

    end_portfolio_value = cerebro.broker.getvalue()
    pnl = end_portfolio_value - start_portfolio_value
    print("Calculated sharpe " + str(sharpe) + " for pair " + symbol1 + "/" + symbol2)
    # print(f'Starting Portfolio Value: {start_portfolio_value:2f}')
    # print(f'Final Portfolio Value: {end_portfolio_value:2f}')
    # print(f'PnL: {pnl:.2f}')

def calculateRatioSeries(file1, file2):
    df1 = pd.read_csv("../data/" + file1)
    filtered1 = df1[(df1['Date'] > TRAIN_START_DATE) & (df1['Date'] < TRAIN_END_DATE)]

    df2 = pd.read_csv("../data/" + file2)
    filtered2 = df2[(df2['Date'] > TRAIN_START_DATE) & (df2['Date'] < TRAIN_END_DATE)]

    intersect = filtered1.index.intersection(filtered2.index)
    return filtered1.loc[intersect]['Close'].values / filtered2.loc[intersect]['Close'].values

def calculateHurst(values, pair):
    hurst_val = hurst(values, range(HURST_LAG_LOWER_LIMIT, HURST_LAG_UPPER_LIMIT))
    if hurst_val >= 0.5:
        print("Skipping as hurst > 0.5 " + pair)
        return -1
    else:
        print("Calculated Hurst for pair " + pair + " : " + str(hurst_val))
        return hurst_val

def groupFilesByAssetType(asset, file_by_asset_type):
    merged = pd.DataFrame()

    for subdir, dirs, files in os.walk("../data/"):
        for file in files:
            if asset not in file:
                continue
            df_cur = pd.read_csv("../data/" + file)
            filtered = df_cur[(df_cur['Date'] > TRAIN_START_DATE) & (df_cur['Date'] < TRAIN_END_DATE)]
            filtered[file.split('_')[1]] = filtered['Close']
            if filtered.empty:
                print("Skipping " + file + "as frame is empty after filtering by date.")
                continue

            if merged.empty:
                merged['Date'] = filtered['Date']
                merged.set_index('Date')
                merged[file.split('_')[1]] = filtered['Close']
            else:
                merged = merged.merge(filtered[['Date', file.split('_')[1]]], on=['Date'], how='inner')
            file_by_asset_type.setdefault(file.split("_")[0], []).append(file)

    return merged

def getResults(asset):
    file_by_asset_type = {}
    average_sharpe_by_asset = {}
    hurst_by_asset = {}

    df = groupFilesByAssetType(asset, file_by_asset_type)
    if asset not in file_by_asset_type:
        return
    del df["Date"]
    scores, p_values, cointegrated_pairs = find_cointegrated_pairs(df)

    for i, file1 in enumerate(file_by_asset_type[asset]):
        for j, file2 in enumerate(file_by_asset_type[asset]):
            if i == j:
                continue

            symbol1 = file1.split('_')[1]
            symbol2 = file2.split('_')[1]
            pair = symbol1 + "/" + symbol2

            try:
                ratio = calculateRatioSeries(file1, file2)
                hurst_val = calculateHurst(ratio, pair)

                # Check if the pair is anti-persistent
                if hurst_val == -1:
                    continue

                # Check if the pair is co-integrated
                if (symbol1, symbol2) not in cointegrated_pairs and (symbol2, symbol1) not in cointegrated_pairs:
                    print("Skipping pair " + pair + " as it is not found to be cointegrated")
                    continue

                sharpe_ratios = []

                for spread_limit in range(SPREAD_LOWER_LIMIT, SPREAD_UPPER_LIMIT):
                    runBacktest(spread_limit, file1, file2, sharpe_ratios)
                calculateAverageSharpeRatio(sharpe_ratios, pair, average_sharpe_by_asset, hurst_by_asset, hurst_val)
            except Exception as e:
                print("Skipping pair " + pair + " as exception was found " + str(e))

    df_results = pd.DataFrame({'Symbol': average_sharpe_by_asset.keys(), 'Sharpe Ratio': average_sharpe_by_asset.values(), 'Hurst': hurst_by_asset.values()})
    df_results.to_csv("pairs_results_" + asset + ".csv")

if __name__ == '__main__':
    getResults('stock')
    getResults('crypto')
    getResults('fx')