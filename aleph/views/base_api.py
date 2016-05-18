import os
import logging
from time import time
from apikit import jsonify
from flask import render_template, current_app, Blueprint, request, session
from jsonschema import ValidationError
from elasticsearch import TransportError

from aleph import event
from aleph.model.constants import CORE_FACETS, SOURCE_CATEGORIES
from aleph.model.constants import COUNTRY_NAMES, LANGUAGE_NAMES
from aleph.model.validation import resolver
from aleph.views.cache import enable_cache

blueprint = Blueprint('base_api', __name__)
log = logging.getLogger(__name__)


@blueprint.before_app_request
def begin_event_track():
    request._aleph_begin = time()


@blueprint.after_app_request
def end_event_track(resp):
    duration = time() - request._aleph_begin
    if request.endpoint == 'static':
        return resp
    origin = 'aleph.views.%s' % request.endpoint
    log.debug("Request %s (%s): %sms", request.endpoint, resp.status_code,
              int(duration * 1000))
    event.report(origin, {
        'endpoint': request.endpoint,
        'duration': duration,
        'url': request.url,
        'query_string': request.query_string,
        'headers': request.headers.items(),
        'role': request.auth_role.id if request.logged_in else None,
        'remote_addr': request.remote_addr,
        'method': request.method,
        'status_code': resp.status_code,
        'response_length': resp.content_length
    })
    log.info('DEBUG OAUTH REQ %r, %r (%r)', request.remote_addr,
             session.get('oauth', {}).get('access_token'),
             request.auth_role)
    # print session.get('oauth', {}).get('access_token')
    return resp


def angular_templates():
    for tmpl_set in ['templates', 'help']:
        partials_dir = os.path.join(current_app.static_folder, tmpl_set)
        for (root, dirs, files) in os.walk(partials_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                with open(file_path, 'rb') as fh:
                    file_name = file_path[len(current_app.static_folder) + 1:]
                    yield (file_name, fh.read().decode('utf-8'))


@blueprint.route('/')
@blueprint.route('/search')
@blueprint.route('/help')
@blueprint.route('/help/<path:path>')
@blueprint.route('/entities')
@blueprint.route('/entities/<path:path>')
@blueprint.route('/tabular/<path:path>')
@blueprint.route('/text/<path:path>')
def ui(**kwargs):
    enable_cache(server_side=True)
    return render_template("layout.html", templates=angular_templates())


@blueprint.route('/api/1/metadata')
def metadata():
    enable_cache(server_side=False)
    schemata = {}
    for schema_id, schema in resolver.store.items():
        if not schema_id.endswith('#'):
            schema_id = schema_id + '#'
        schemata[schema_id] = {
            'id': schema_id,
            'title': schema.get('title'),
            'faIcon': schema.get('faIcon'),
            'plural': schema.get('plural', schema.get('title')),
            'description': schema.get('description'),
            'inline': schema.get('inline', False)
        }
    return jsonify({
        'status': 'ok',
        'fields': CORE_FACETS,
        'source_categories': SOURCE_CATEGORIES,
        'countries': COUNTRY_NAMES,
        'languages': LANGUAGE_NAMES,
        'schemata': schemata
    })


@blueprint.app_errorhandler(403)
def handle_authz_error(err):
    return jsonify({
        'status': 'error',
        'message': 'You are not authorized to do this.',
        'roles': request.auth_roles,
        'user': request.auth_role
    }, status=403)


@blueprint.app_errorhandler(ValidationError)
def handle_validation_error(err):
    return jsonify({
        'status': 'error',
        'message': err.message
    }, status=400)


@blueprint.app_errorhandler(TransportError)
def handle_es_error(err):
    return jsonify({
        'status': 'error',
        'message': err.error,
        'info': err.info.get('error', {}).get('root_cause', [])[-1]
    }, status=400)
