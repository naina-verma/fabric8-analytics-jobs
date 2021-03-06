from sqlalchemy import desc
from dateutil.parser import parse as parse_datetime
from selinon import StoragePool
from cucoslib.models import WorkerResult, Analysis

from .base import BaseHandler


class AggregateTopics(BaseHandler):
    """Aggregate gathered topics and store them on S3."""

    def _store_topics(self, bucket_name, object_key, report):
        self.log.info("Storing aggregated topics on S3")
        s3_destination = StoragePool.get_connected_storage('AmazonS3')

        # hack for temporary change bucket name so we have everything set up
        old_bucket_name = s3_destination.bucket_name
        try:
            s3_destination.bucket_name = bucket_name
            s3_destination.store_dict(report, object_key)
        finally:
            s3_destination.bucket_name = old_bucket_name

    def execute(self, ecosystem, bucket_name, object_key, from_date=None, to_date=None):
        """Aggregate gathered topics and store them on S3.
        
        :param ecosystem: ecosystem name for which topics should be gathered
        :param bucket_name: name of the destination bucket to which topics should be stored
        :param object_key: name of the object under which aggregated topics should be stored
        :param from_date: date limitation for task result queries
        :param to_date: date limitation for taks result queries
        """
        if from_date is not None:
            from_date = parse_datetime(from_date)
        if to_date is not None:
            to_date = parse_datetime(to_date)

        s3 = StoragePool.get_connected_storage('S3Data')
        # TODO: this will need to be changed once we will introduce package level flows
        postgres = StoragePool.get_connected_storage('BayesianPostgres')

        base_query = postgres.session.query(WorkerResult).\
            join(Analysis).\
            filter(WorkerResult.error.is_(False)).\
            filter(WorkerResult.worker == 'github_details')

        if from_date is not None:
            base_query = base_query.filter(Analysis.started_at > from_date).\
                order_by(desc(WorkerResult.id))

        if to_date is not None:
            base_query = base_query.filter(Analysis.started_at < to_date).\
                order_by(desc(WorkerResult.id))

        start = 0
        topics = []
        while True:
            results = base_query.slice(start, start + 10).all()

            if not results:
                break

            self.log.info("Collecting topics, slice offset is %s", start)
            start += 10

            for entry in results:
                name = entry.package.name
                version = entry.package.version

                task_result = entry.task_result
                if not postgres.is_real_task_result(task_result):
                    task_result = s3.retrieve_task_result(ecosystem, name, version, 'github_details')

                topics.append({
                    'topics': task_result.get('details', {}).get('topics'),
                    'name': name,
                    'ecosystem': ecosystem,
                    'version': version
                })

        report = {
            'ecosystem': ecosystem,
            'bucket_name': bucket_name,
            'object_key': object_key,
            'from_date': str(from_date),
            'to_date': str(to_date),
            'result': topics
        }
        self._store_topics(bucket_name, object_key, report)
