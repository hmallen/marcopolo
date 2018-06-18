import datetime
import logging
import os
import sys
import time

from poloniex import Poloniex
from pymongo import MongoClient

from ticker import Ticker

mongo_ip = 'mongodb://192.168.1.179:27017/'

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class MarcoPolo:
    def __init__(self, config_path):
        import configparser

        config = configparser.ConfigParser()
        config.read(config_path)

        polo_api = config['poloniex']['api']
        polo_secret = config['poloniex']['secret']

        self.polo = Poloniex(polo_api, polo_secret)

        self.db = MongoClient(mongo_ip).marcopolo['trades']

        #self.ticker = MongoClient(mongo_ip).poloniex['ticker']
        self.ticker = Ticker(mongo_ip)


    def create_trade(self, market, buy_target, profit_level, stop_level, stop_price=None,
                     spend_proportion=0.01, price_tolerance=0.001, entry_timeout=5, taker_fee_ok=True):
        create_trade_successful = True

        try:
            self.market = market
            logger.debug('self.market: ' + self.market)

            self.base_currency = self.market.split('_')[0]
            logger.debug('self.base_currency: ' + self.base_currency)

            self.trade_currency = self.market.split('_')[1]
            logger.debug('self.trade_currency: ' + self.trade_currency)

            self.buy_target = buy_target
            logger.debug('self.buy_target: ' + str(self.buy_target))

            self.buy_max = round(self.buy_target * (1 + price_tolerance), 8)
            logger.debug('self.buy_max: ' + str(self.buy_max))

            self.spend_proportion = spend_proportion
            logger.debug('self.spend_proportion: ' + str(self.spend_proportion))

            try:
                balance_base_currency = self.polo.returnAvailableAccountBalances()['exchange'][self.base_currency]
                logger.debug('balance_base_currency: ' + str(balance_base_currency))

            except:
                logger.error(self.base_currency + ' balance currently 0. Unable to continue with trade. Exiting.')

                create_trade_successful = False

                sys.exit(1)

            self.spend_amount = round(balance_base_currency * self.spend_proportion, 8)
            logger.debug('self.spend_amount: ' + str(self.spend_amount))

            #self.buy_amount_target = round(self.spend_amount * self.buy_target, 8)
            #logger.debug('self.buy_amount_target: ' + str(self.buy_amount_target))

            self.profit_level = profit_level
            logger.debug('self.profit_level: ' + str(self.profit_level))

            self.sell_price = round(self.buy_target * (1 + self.profit_level), 8)
            logger.debug('self.sell_price: ' + str(self.sell_price))

            self.stop_level = stop_level
            logger.debug('self.stop_level: ' + str(self.stop_level))

            if stop_price == None:
                self.stop_price = round(self.buy_target * (1 - self.stop_level), 8)
                logger.debug('self.stop_price: ' + str(self.stop_price))

            else:
                if stop_price < self.buy_target:
                    self.stop_price = stop_price

                else:
                    logger.error('Invalid parameters. Stop price set equal to or greater than buy target.')

                    create_trade_result = False

            self.abort_time = datetime.datetime.now() + datetime.timedelta(minutes=entry_timeout)
            logger.debug('self.abort_time: ' + str(self.abort_time))

            fee_info = self.polo.returnFeeInfo()

            self.maker_fee = fee_info['makerFee']
            logger.debug('self.maker_fee: ' + str(self.maker_fee))

            self.taker_fee = fee_info['takerFee']
            logger.debug('self.taker_fee: ' + str(self.taker_fee))

            trade_doc = dict(market=self.market, time=datetime.datetime.now(),
                             buy=dict(target=self.buy_target,
                                      max=self.buy_max,
                                      spend=self.spend_amount,
                                      price_actual=None,
                                      amount_actual=None,
                                      abort_time=self.abort_time,
                                      complete=False,
                                      order_number=None),
                             sell=dict(target=self.sell_price,
                                       stop=self.stop_price,
                                       actual=None,
                                       complete=False,
                                       order_number=None),
                             fees=dict(maker=self.maker_fee, taker=self.taker_fee),
                             parameters=dict(market=market,
                                             buy_target=buy_target,
                                             profit_level=profit_level,
                                             stop_level=stop_level,
                                             stop_price=stop_price,
                                             spend_proportion=spend_proportion,
                                             price_tolerance=price_tolerance,
                                             entry_timeout=entry_timeout,
                                             taker_fee_ok=taker_fee_ok))

            logger.info('Creating MongoDB trade document.')

            try:
                self.db.update_one(
                    {'_id': self.market},
                    {'$set': trade_doc},
                    upsert=True
                )

            except Exception as e:
                logger.exception('Exception while creating MongoDB trade document.')
                logger.exception(e)

                create_trade_successful = False

        except Exception as e:
            logger.exception('Exception in create_trade().')
            logger.exception(e)

            create_trade_successful = False

        finally:
            return create_trade_successful


    def run_trade_cycle(self):
        try:
            # If market price above (buy target * (1 - price_tolerance)), set limit sell
            # If market price below (buy target * (1 - price_tolerance)), remove limit sell and place stop-loss

            ## Entry buy ##
            entry_buy_complete = False

            while entry_buy_complete == False:
                if self.taker_fee_ok == True:
                    # Place immediateOrCancel buy at lowest ask
                    # If spend amount filled, break
                    # If not, check if next lowest ask below max buy price
                    # If yes, place another immediateOrCancel buy at lowest ask
                    # Continue until spend amount fulfilled or timeout

                    lowest_ask = self.ticker(self.market)['lowestAsk']

                    if lowest_ask <= self.buy_max:
                        result = polo.buy(currencyPair=self.market, immediateOrCancel=True)

                else:
                    pass

                if datetime.datetime.now() >= self.abort_time:
                    logger.warning('Entry buy not completed before timeout reached.')

                    # IF PARTIAL BUY MADE
                    #entry_buy_complete = True
                    #logger.warning('Continuing trade cycle with partial buy.')

                    # IF NO PARTIAL BUY MADE
                    #logger.warning('Removing trade document and exiting.')

            if entry_buy_complete == True:
                pass

            """
            for x in range(0, 30):
                tick = self.ticker(self.market)
                logger.debug('tick: ' + str(tick))

                time.sleep(0.5)
            """

        except Exception as e:
            logger.exception('Exception in exec_trade().')
            logger.exception(e)


if __name__ == '__main__':
    # __init__(self, config_path)
    # create_trade(self, market, buy_target, profit_level, stop_level, stop_price=None, spend_proportion, price_tolerance=0.001, entry_timeout=5)
    polo = Poloniex()

    test_config_path = '../config/config_polo.ini'

    marcopolo = MarcoPolo(config_path=test_config_path)

    test_market = 'BTC_STR'
    logger.debug('test_market: ' + test_market)
    test_buy_target = polo.returnTicker()['BTC_STR']['last']
    logger.debug('test_buy_target: ' + str(test_buy_target))
    test_profit_level = 0.015
    logger.debug('test_profit_level: ' + str(test_profit_level))
    test_stop_level = 0.01
    logger.debug('test_stop_level: ' + str(test_stop_level))
    test_spend_proportion = 0.01
    logger.debug('test_spend_proportion: ' + str(test_spend_proportion))
    test_entry_timeout = 5
    logger.debug('test_entry_timeout: ' + str(test_entry_timeout))

    create_trade_result = marcopolo.create_trade(market=test_market, buy_target=test_buy_target,
                                                 profit_level=test_profit_level, stop_level=test_stop_level,
                                                 spend_proportion=test_spend_proportion, entry_timeout=test_entry_timeout)
    logger.debug('create_trade_result: ' + str(create_trade_result))

    if create_trade_result == True:
        marcopolo.run_trade_cycle()
