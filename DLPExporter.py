# !/usr/bin/env python3
import multiprocessing
import os
import sys
import time

from past.builtins import raw_input

import botocore
import pyodbc
import requests

import ASFFMapper as Mapper
import DatabaseConnector
from CloudHandlers.AzureDataCollector import AzureDataCollector, is_azure_configured
from CloudHandlers.SecurityHubTool import amazon_security_hub, insight_creator, amazon_security_hub_xml, \
    enable_security_hub, enable_import_findings_for_product
from Config import Configurations, DatabaseConnection
from xmltodict import parse
from threading import Thread
import argparse
from loguru import logger


class ManualAWS(Thread):

    def __init__(self, logger_obj_aws_manual):
        Thread.__init__(self)
        self.logger_obj = logger_obj_aws_manual
        self.daemon = True
        self.start()

    def run(self):
        while True:
            location = Configurations.get_configurations()['file_location']

            for file in os.listdir(location):
                if file.endswith(".xml") and file.startswith("event"):
                    with open(os.path.join(location, file)) as fd:
                        doc = parse(fd.read())

                        xml_file_name = location + '/event-' + doc['evt:event']['evt:event_info'][
                            'evt:incidentId'] + '.xml'

                        json_file = Mapper.map_xml_to_asff(doc)

                        fd.close()

                        # Dont send empty files
                        if (len(json_file)) >= 1:
                            amazon_security_hub_xml(json_file, xml_file_name, self.logger_obj)
                        else:
                            os.remove(xml_file_name)
            time.sleep(10)


class AzureAutoCheck(Thread):

    def __init__(self, logger_):
        Thread.__init__(self)
        self.logger_ = logger_
        self.azure_data_collector = AzureDataCollector(logger_)
        self.daemon = True
        self.start()

    def run(self):
        while True:
            try:
                if self.azure_data_collector.health_check():
                    try:
                        json_file, offset_time = Mapper.map_sql_to_azure()
                    except Exception as e:
                      
                        self.logger_.error(f"Error Database May not have been initialized")

                        json_file = None

                    if not json_file:
                        # self.logger_.info("No Data received, azure thread is sleeping for 5 minutes before retrying")
                        time.sleep(300)
                    elif (len(json_file)) >= 1:
                        self.azure_data_collector.send(json_file, offset_time)
                else:
                    self.logger_.error("Azure cannot be reached, azure thread is sleeping for 5 minutes before "
                                          "retrying")
                    time.sleep(300)
            except (requests.exceptions.RequestException, RuntimeError, ValueError) as e:
                self.logger_.error(f'{e}: error occurred, Azure thread is sleeping for 5 minutes before retrying')
                time.sleep(300)


class AWSAutoCheck(Thread):

    def __init__(self, logger_):
        Thread.__init__(self)
        self.daemon = True
        self.start()
        self.logger_ = logger_

    def run(self):

        while True:

            try:
                json_file, offset_time = Mapper.map_sql_to_asff()
            except Exception as e:
                self.logger_.error(f"Error Database May not have been initialized")

                json_file = None

            if not json_file:
                # self.logger_.info("No Data received, aws thread is sleeping for 5 minutes before retrying")
                time.sleep(300)
            elif (len(json_file)) >= 1:
                try:
                    amazon_security_hub(json_file, offset_time, self.logger_)
                except botocore.exceptions.ReadTimeoutError as exception:
                    self.logger_.error(f'{exception}: error occurred, AWS thread is sleeping for 5 minutes before '
                                          f'retrying')
                    time.sleep(300)


class CreateInsight(Thread):

    def __init__(self, logger_):
        Thread.__init__(self)
        self.logger_ = logger_
        self.daemon = True
        self.start()

    def run(self):
        insight_creator(self.logger_)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='DLPExporter')
    parser.add_argument('--login', action="store", dest='login', default='0')
    args = parser.parse_args()
    config = Configurations.get_configurations()
    if args.login != '0':
        username = input("Please enter your Database username: ")
        password = input("Please enter your Database password: ")
        DatabaseConnection.save_password(password, username)
        sys.exit(0)

    file_path = f'./logs/ForcepointDLPEvents.log'
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    logger.configure(
        handlers=[{"sink": file_path, 'format': "{time:YYYY-MM-DD at HH:mm:ss} | {level} | {message}",
                   "level": "INFO", 'rotation': "500 MB", 'enqueue': True, 'retention': 5}])

    logger_args = logger

    try:
        if config['AwsAccountId'] and config['aws_access_key_id'] and config['aws_secret_access_key'] \
                and config['region_name']:
            logger.info('AWS is configured on')
            try:
                if DatabaseConnection.get_connection() != 'none':
                    enable_security_hub()
                    enable_import_findings_for_product()
                    db_ver = DatabaseConnector.execute_sql('SELECT @@version').fetchall()
                    logger.info(f'Database Connection established - AWS thread starting - {db_ver[0][0]}')
                    CreateInsight(logger_args)
                    # ManualAWS(logger_obj)
                    AWSAutoCheck(logger_args)

            except pyodbc.Error as ex:
                logger.error(ex.args[1])
        else:
            logger.info("configure the config.json if you need AWS")
    except KeyError:
        logger.info("Ignore if not using Security Hub. Some fields are missing from the config (AwsAccountId, "
                        "aws_access_key_id, aws_secret_access_key, region_name)")

    try:
        if is_azure_configured(config):
            logger.info('Azure is configured on')

            try:
                if DatabaseConnection.get_connection() != 'none':
                    db_ver = DatabaseConnector.execute_sql('SELECT @@version').fetchall()
                    logger.info(f'Database Connection established - Azure thread starting - {db_ver[0][0]}')
                    AzureAutoCheck(logger_args)
                else:
                    logger.info('Database Connection cannot be established, please check your installation')

            except pyodbc.Error as ex:
                logger.error(ex.args[1])
        else:
            logger.info("Configure AzureIngestionMode and the corresponding Azure settings in config.json")
    except KeyError:
        logger.info("Ignore if not using Sentinel. Required Azure settings are missing from config.json")

    raw_input('')
