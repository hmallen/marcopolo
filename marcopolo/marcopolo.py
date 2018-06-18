import configparser
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
    def __init__(self, config_path, ws_ticker=True):
        config = configparser.ConfigParser()
        config.read(config_path)

        polo_api = config['poloniex']['api']
        polo_secret = config['poloniex']['secret']

        self.polo = Poloniex(polo_api, polo_secret)

        self.db = MongoClient(mongo_ip).marcopolo['trades']

        #self.ticker = MongoClient(mongo_ip).poloniex['ticker']
        self.ticker = Ticker(mongo_ip)

        self.ws_ticker = ws_ticker


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
                                      spend_actual=None,
                                      amount_actual=None,
                                      price_actual=None,
                                      abort_time=self.abort_time,
                                      complete=False,
                                      orders=[]),
                             sell=dict(target=self.sell_price,
                                       amount=None,
                                       stop=self.stop_price,
                                       threshold=None,
                                       actual=None,
                                       complete=False,
                                       order_number=None,
                                       stop_active=None,
                                       orders=[]),
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
            trade_doc = self.db.find_one({'_id': self.market})

            ## Entry buy ##
            entry_buy_complete = False

            # GET TRADE DOC

            spend_total = 0
            amount_total = 0

            while entry_buy_complete == False:
                try:
                    if self.taker_fee_ok == True:
                        # Place immediateOrCancel buy at lowest ask
                        # If spend amount filled, break
                        # If not, check if next lowest ask below max buy price
                        # If yes, place another immediateOrCancel buy at lowest ask
                        # Continue until spend amount fulfilled or timeout

                        if self.ws_ticker == True:
                            lowest_ask = self.ticker(self.market)['lowestAsk
                        else:
                            lowest_ask = self.polo.returnTicker()[self.market]['lowestAsk']
                        logger.debug('lowest_ask: ' + str(lowest_ask))

                        if lowest_ask <= self.buy_max:
                            buy_amount = round(lowest_ask * (trade_doc['buy']['spend'] - spend_total), 8)
                            logger.debug('buy_amount: ' + str(buy_amount))

                            if buy_amount <= 0:
                                logger.info('Buy amount satisfied.')

                                entry_buy_complete = True

                                break

                            result = polo.buy(currencyPair=self.market, rate=lowest_ask, amount=buy_amount, immediateOrCancel=1)

                            if len(result['resultingTrades']) > 0:
                                trade_doc['buy']['orders'].append(result)

                                for trade in result['resultingTrades']:
                                    spend_total += trade['total']
                                    amount_total += trade['amount']

                                if result['amountUnfilled'] == 0:
                                    logger.info('Entry buy complete.')

                                    entry_buy_complete = True

                                else:
                                    logger.info('Partial buy filled. Continuing.')

                            else:
                                logger.info('Buy not executed at requested price. Recalculating and trying again.')

                    else:
                        # Create "BFB" order that follows price
                        pass

                    if datetime.datetime.now() >= self.abort_time:
                        logger.warning('Entry buy not completed before timeout reached.')

                        # If no buys executed
                        if spend_total == 0:
                            logger.warning('No buys executed. Removing trade document and exiting.')

                            delete_result = self.db.delete_one({'_id': self.market})
                            logger.debug('delete_result: ' + str(delete_result))

                            break

                        else:
                            entry_buy_complete = True

                            logger.warning('Continuing trade cycle with partial buy amount.')

                    time.sleep(0.2)     # To keep API calls to under 6 per second (very conservatively)

                except Exception as e:
                    logger.exception('Exception while placing entry buy.')
                    logger.exception(e)

            if entry_buy_complete == True:
                trade_doc['buy']['spend_actual'] = spend_total
                trade_doc['buy']['amount_actual'] = amount_total
                trade_doc['buy']['price_actual'] = round(spend_total / amount_total, 8)

                trade_doc['buy']['complete'] = True

                trade_doc['sell']['amount'] = amount_total

                update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc}, upsert=True)
                logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

            else:
                # Delete the trade doc and exit
                logger.warning('Could not complete any portion of entry buy. Exiting.')

                sys.exit()

            trade_doc = self.db.find_one({'_id': self.market})

            while (True):
                try:
                    ## Place sell order ##
                    result = polo.sell(currencyPair=self.market, rate=self.sell_price, amount=trade_doc['sell']['target'])

                    trade_doc['sell']['order'] = result['orderNumber']

                    trade_doc['sell']['orders'].append(result)

                    update_result - self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                    logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                    logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                    break

                except Exception as e:
                    logger.exception(e)

                    logger.warning('Failed to place sell order. Retrying in 30 seconds.')

                    time.sleep(30)

            logger.info('Sell order placed at ' + str(self.sell_price) + ' ' + self.base_currency + '.')

            ## Monitor conditions in real-time

            stop_active = False

            trade_doc['sell']['stop_active'] = stop_active

            if trade_doc['buy']['price_actual'] < self.buy_target:
                baseline = trade_doc['buy']['price_actual']

            else:
                baseline = self.buy_target

            self.threshold = round(baseline - ((baseline - self.stop_price) * self.price_tolerance), 8)

            trade_doc['sell']['threshold'] = self.threshold
            logger.debug('trade_doc[\'sell\'][\'threshold\']: ' + str(trade_doc['sell']['threshold']))

            update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
            logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
            logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

            while (True):
                try:
                    ## Monitor price and execute stop-loss if necessary ##

                    # If market price above (buy_target * (1 - price_tolerance)), set limit sell
                    # If market price below (buy_target * (1 - price_tolerance)), remove limit sell and monitor for stop-loss execution trigger

                    # Limit sell currently on book
                    if stop_active == False:
                        if self.ws_ticker == True:
                            highest_bid = self.ticker(self.market)['highestBid']
                        else:
                            highest_bid = self.polo.returnTicker()[self.market]['highestBid']
                        logger.debug('highest_bid: ' + str(highest_bid))

                        if highest_bid < self.threshold:
                            while (True):
                                # Remove sell order
                                cancel_result = polo.cancelOrder(trade_doc['sell']['order'])
                                logger.debug('cancel_result: ' + str(cancel_result))

                                logger.info(cancel_result['message'])

                                if cancel_result['success'] == 1:
                                    trade_doc['sell']['orders'].append(cancel_result)

                                    logger.info('Sell order cancelled successfully.')

                                    logger.info('Setting stop-loss monitor to active.')

                                    stop_active = True

                                    trade_doc['sell']['stop_active'] = True

                                    update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                    logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                    logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                                    break

                    ## Stop-loss monitoring active
                    else:
                        while (True):
                            # Monitor for stop-loss condition and execute if necessary
                            if self.ws_ticker == True:
                                highest_bid = self.ticker(self.market)['highestBid']
                            else:
                                highest_bid = polo.returnTicker()[self.market]['highestBid']
                            logger.debug('highest_bid: ' + str(highest_bid))

                            if highest_bid > self.threshold:
                                while (True):
                                    try:
                                        ## Place sell order ##
                                        result = polo.sell(currencyPair=self.market, rate=self.sell_price, amount=trade_doc['sell']['target'])

                                        trade_doc['sell']['order'] = result['orderNumber']

                                        update_result - self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                        logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                        logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                                        break

                                    except Exception as e:
                                        logger.exception(e)

                                        logger.warning('Failed to place sell order. Retrying in 30 seconds.')

                                        time.sleep(30)

                                logger.info('Sell order placed at ' + str(self.sell_price) + ' ' + self.base_currency + '.')

                                logger.info('Setting stop-loss monitor to inactive.')

                                stop_active = False

                                trade_doc['sell']['stop_active'] = False

                                update_result = self.db.update_one({'_id': self.market}, {'$set': trade_doc})
                                logger.debug('update_result.matched_count: ' + str(update_result.matched_count))
                                logger.debug('update_result.modified_count: ' + str(update_result.modified_count))

                            elif highest_bid <= (self.stop_price * (1 + self.price_tolerance)):
                                # Begin orderbook checks for stop-loss triggering
                                if self.ws_ticker == True:
                                    highest_bid = self.ticker(self.market)['highestBid']
                                else:
                                    highest_bid = polo.returnTicker()[self.market]['highestBid']
                                logger.debug('highest_bid: ' + str(highest_bid))

                                while highest_bid <= (self.stop_price * (1 + self.price_tolerance)):
                                    ob = polo.returnOrderBook(currencyPair=self.market)

                                    amount_total = 0
                                    for bid in ob['bids']:
                                        amount_total += bid[1]

                                        if amount_total >= trade_doc['sell']['amount']:
                                            if bid[0] <= self.stop_price:
                                                ## Execute stop-loss order ##

                                                sell_price = self.stop_price

                                                sold_total = 0

                                                while (True):
                                                    if self.ws_ticker == True:
                                                        highest_bid = ticker(self.market)['highestBid']
                                                    else:
                                                        highest_bid = self.polo.returnTicker()[self.market]
                                                    logger.debug('highest_bid: ' + str(highest_bid))

                                                    if highest_bid < sell_price:
                                                        sell_price = highest_bid

                                                    result = polo.sell(currencyPair=self.market, rate=sell_price,
                                                                       amount=trade_doc['sell']['amount'], immedateOrCancel=1)

                                                    if len(result['resultingTrades']) > 0:
                                                        trade_doc['sell']['orders'].append(result)

                                                        for trade in result['resultingTrades']:
                                                            sold_total += trade['amount']

                                                        if result['amountUnfilled'] == 0:
                                                            logger.info('Stop-loss order executed successfully.')

                                                            break

                                                        else:
                                                            logger.info('Sell partially filled. Continuing.')

                                                    else:
                                                        logger.info('Sell not executed at requested price. Recalculating and trying again.')

                                    time.sleep(0.2)


                    time.sleep(0.2)

                except Exception as e:
                    logger.exception('Exception while monitoring sell conditions.')
                    logger.exception(e)

        except Exception as e:
            logger.exception('Exception in run_trade_cycle().')
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
