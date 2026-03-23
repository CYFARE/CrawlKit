from crawlkit.webadmin.api.jobs import setup_job_routes
from crawlkit.webadmin.api.results import setup_result_routes
from crawlkit.webadmin.api.profiles import setup_profile_routes
from crawlkit.webadmin.api.seeds import setup_seed_routes
from crawlkit.webadmin.api.campaigns import setup_campaign_routes


def setup_api_routes(app):
    setup_job_routes(app)
    setup_result_routes(app)
    setup_profile_routes(app)
    setup_seed_routes(app)
    setup_campaign_routes(app)
