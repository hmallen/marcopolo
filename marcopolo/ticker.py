import websocket
from pymongo import MongoClient

from poloniex import Poloniex

from multiprocessing.dummy import Process as Thread
import json
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class wsTicker(object):

    def __init__(self):
        self.api = Poloniex()

        self.db = MongoClient('mongodb://192.168.1.179:27017/').poloniex['ticker']

        self.db.drop()

        self.ws = websocket.WebSocketApp("wss://api2.poloniex.com/",
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close)

        self.ws.on_open = self.on_open


    def __call__(self, market=None):
        """ returns ticker from mongodb """
        if market:
            return self.db.find_one({'_id': market})

        return list(self.db.find())


    def on_message(self, ws, message):
        message = json.loads(message)

        if 'error' in message:
            #print(message['error'])
            logger.error(message['error'])

            return

        if message[0] == 1002:
            if message[1] == 1:
                #print('Subscribed to ticker')
                logger.debug('Subscribed to ticker.')

                return

            if message[1] == 0:
                #print('Unsubscribed to ticker')
                logger.debug('Unsubscribed from ticker.')

                return

            data = message[2]

            self.db.update_one(
                {"id": float(data[0])},
                {"$set": {'last': data[1],
                          'lowestAsk': data[2],
                          'highestBid': data[3],
                          'percentChange': data[4],
                          'baseVolume': data[5],
                          'quoteVolume': data[6],
                          'isFrozen': data[7],
                          'high24hr': data[8],
                          'low24hr': data[9]
                          }},
                upsert=True)


    def on_error(self, ws, error):
        #print(error)
        logger.error(error)


    def on_close(self, ws):
        #print("Websocket closed!")
        logger.debug('Websocket closed.')


    def on_open(self, ws):
        tick = self.api.returnTicker()

        for market in tick:
            self.db.update_one(
                {'_id': market},
                {'$set': tick[market]},
                upsert=True)

        #print('Populated markets database with ticker data')
        logger.debug('Populated markets database with ticker data.')

        self.ws.send(json.dumps({'command': 'subscribe',
                                 'channel': 1002}))


    def start(self):
        self.t = Thread(target=self.ws.run_forever)

        self.t.daemon = True

        self.t.start()

        #print('Thread started')
        logger.debug('Thread started.')


    def stop(self):
        self.ws.close()

        self.t.join()

        #print('Thread joined')
        logger.debug('Thread joined.')


if __name__ == "__main__":
    try:
        # websocket.enableTrace(True)

        ticker = wsTicker()

        ticker.start()

        while (True):
            try:
                time.sleep(0.1)

            except Exception as e:
                logger.exception('Exception in inner loop.')
                logger.exception(e)

            except KeyboardInterrupt:
                logger.info('Exit signal raised in inner try/except. Breaking from inner loop.')

                break

        logger.info('Exited inner loop.')

        """
        for i in range(5):
            sleep(10)
            pprint.pprint(ticker('USDT_BTC'))
            pprint.pprint(ticker('BTC_STR'))
            pprint.pprint(ticker('USDT_STR'))
        ticker.stop()
        """

    except Exception as e:
        logger.exception('Exception in outer loop.')
        logger.exception(e)

    except KeyboardInterrupt:
        logger.info('Exit signal raised in outer try/except.')

    finally:
        logger.info('Shutting down ticker.')

        ticker.stop()

        logger.info('Exiting.')
