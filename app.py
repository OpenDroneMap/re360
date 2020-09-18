# Server is setup here
from flask import Flask, session, render_template, redirect, request, jsonify, current_app
from flask_bootstrap import Bootstrap
import time, os
import psycopg2

from odm360.utils import parse_config, make_config
from odm360.log import start_logger
import odm360.camera360rig as camrig
from odm360.utils import get_lan_ip
from odm360 import dbase
# API for picam is defined below
def do_GET():
    """
    GET API should provide a json with the following fields:
    state: str - can be:
        "idle" - before anything is done, or after camera is stopped (to be implemented with push button)
        "ready" - camera is initialized
        "capture" - camera is capturing
    req: str - name of method to call from server
    kwargs: dict - any kwargs that need to be parsed to method (can be left out if None)
    log: str - log message to be printed from client on server's log (see self.logger)

    the GET API then decides what action should be taken given the state.
    Client is responsible for updating its status to the current
    """
    try:
        # TODO: pass full project details from dbase to child
        msg = request.get_json()
        print(msg)
        # Create or update state of current camera
        current_app.config['rig'].cam_state[request.remote_addr] = msg['state']
        log_msg = f'Cam {request.remote_addr} - GET {msg["req"]}'
        logger.debug(log_msg)
        # check if task exists and sent instructions back
        method = f'get_{msg["req"].lower()}'
        # if hasattr(self, method):
        if 'kwargs' in msg:
            kwargs = msg['kwargs']
        else:
            kwargs = {}
        task = getattr(current_app.config['rig'], method)
        # execute with key-word arguments provided
        r = task(**kwargs)
        return r
    except:
        return {'task': 'wait',
                'kwargs': {}
                }

# POST echoes the message adding a JSON field
def do_POST():
    """
    POST API should provide a json with the following fields:
    req: str - name of method for posting to call from server (e.g. log)
    kwargs: dict - any kwargs that need to be parsed to method (can be left out if None)
    the POST API then decides what action should be taken based on the POST request.
    POST API will also return a result back
    """
    msg = request.get_json()
    print(msg)
    # show request in log
    log_msg = f'Cam {request.remote_addr} - POST {msg["req"]}'

    logger.debug(log_msg)

    # check if task exists and sent instructions back
    method = f'post_{msg["req"].lower()}'
    if hasattr(current_app.config['rig'], method):
        if 'kwargs' in msg:
            kwargs = msg['kwargs']
        else:
            kwargs = {}
        task = getattr(current_app.config['rig'], method)
        # execute with key-word arguments provided
        r = task(**kwargs)
        return r

def cleanopts(optsin):
    """Takes a multidict from a flask form, returns cleaned dict of options"""
    opts = {}
    d = optsin
    for key in d:
        opts[key] = optsin[key].lower().replace(' ', '_')
    return opts

# TODO: remove when database connection is function
def initialize_config(config_fn):
    config = parse_config(config_fn)
    # test if we are ready to start devices or not
    start_parent = True
    if config.get('main', 'n_cams') == '':
        start_parent = False
        logger.info('n_cams is missing in config, starting without a running parent server')
    if config.get('main', 'dt') == '':
        start_parent = False
        logger.info('dt is missing in config, starting without a running parent server')
    if config.get('main', 'project') == '':
        start_parent = False
        logger.info('project is missing in config, starting without a running parent server')
    if config.get('main', 'root') == '':
        start_parent = False
        logger.info('root is missing in config, starting without a running parent server')
    current_app.config['config'] = dict(config.items('main'))
    current_app.config['ip'] = get_lan_ip()
    current_app.config['start_parent'] = start_parent

db = 'dbname=odm360 user=odm360 host=localhost password=zanzibar'
conn = psycopg2.connect(db)
cur = conn.cursor()

# initialize project and photos table if they don't already exist
dbase.create_table_projects(cur)
dbase.create_table_photos(cur)
dbase.create_table_project_active(cur)
dbase.create_table_devices(cur)

logger = start_logger("True", "False")

# if there is an active project, put status on zero (waiting for cams) at the beginning no matter what
cur_project = dbase.query_project_active(cur)
if len(cur_project) == 1:
    dbase.update_project_active(cur, 0)

app = Flask(__name__)
bootstrap = Bootstrap(app)


@app.route("/", methods=['GET', 'POST'])
def gps_page():
    if request.method == "POST":
        form = cleanopts(request.form)
        if 'project' in form:
            logger.info(f"Changing to project {form['project']}")
            # first drop the current active project table and create a new one
            dbase.create_table_project_active(cur, drop=True)
            # insert new active project
            dbase.insert_project_active(cur, int(form['project']))
        elif 'service' in form:
            if form["service"] == "on":
                logger.info("Starting service")
                dbase.update_project_active(cur, 1)  # status 1 means auto_start cameras once they are all online
        else:
            # TODO: bug in code. EWhen switch is turned off, the form returns empty dictionary.
            logger.info("Stopping service")
            dbase.update_project_active(cur, 0)  # status 1 means auto_start cameras once they are all online

    # FIXME: replace by checking for projects in database
    # first check what projects already exist and list those in the status page as selectors
    projects = dbase.query_projects(cur)
    project_ids = [p[0] for p in projects]
    project_names = [p[1] for p in projects]
    projects = zip(project_ids, project_names)
    cur_project = dbase.query_project_active(cur)
    devices_ready = dbase.query_devices(cur, status=1)
    devices_total = dbase.query_devices(cur)

    if len(cur_project) == 0:
        cur_project_id = None
        service_active = 0
    else:
        cur_project_id = cur_project[0][0]
        service_active = cur_project[0][1]
    return render_template("status.html",
                           projects=projects,
                           cur_project_id=cur_project_id,
                           service_active=service_active,
                           devices_total=len(devices_total),
                           devices_ready=len(devices_ready)
                           )  #

@app.route('/project', methods=['GET', 'POST'])
def project_page():
    """
        The settings page where you can manage the various services, the parameters, update, power...
    """
    if request.method == 'POST':
        # config = current_app.config['config']
        # FIXME: put inputs into the database and remove config stuff below
        form = cleanopts(request.form)
        config = {}
        # set the config options as provided

        dbase.insert_project(cur, form['project_name'], n_cams=int(form['n_cams']), dt=int(form['dt']))
        # remove the current project selection and make a fresh table
        dbase.create_table_project_active(cur, drop=True)
        # set project to current by retrieving its id and inserting that in current project table
        project_id = dbase.query_projects(cur, project_name=form['project_name'])[0][0]
        dbase.insert_project_active(cur, project_id=project_id)

        return redirect("/")

    else:
        return render_template("project.html")

@app.route('/logs')
def logs_page():
    """
        The data web pages where you can download/delete the raw gnss data
    """
    return render_template("logs.html")

@app.route('/settings')
def settings_page():
    """
        The data web pages where you can download/delete the raw gnss data
    """
    return render_template("settings.html")

@app.route('/cams')
def cam_page():
    """
        The data web pages where you can download/delete the raw gnss data
    """
    return render_template("cam_status.html", n_cams=range(6))

@app.route('/file_page')
def file_page():
    return render_template("file_page.html")

@app.route('/picam', methods=['GET', 'POST'])
def picam():
    if request.method == 'POST':

        r = do_POST()
    else:
        # print(request.get_json())
        r = do_GET()  # response is passed back to client
    return jsonify(r)

def run(app):
    app.run(debug=False, port=5000, host="0.0.0.0")

if __name__ == "__main__":
    run(app)