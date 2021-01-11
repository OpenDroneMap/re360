import logging
import time
from flask import request
import datetime
from odm360 import dbase, utils
from odm360.states import states
import odm360.camera360rig as camrig

logger = logging.getLogger(__name__)

# API for picam is defined below
def do_request(cur, method="GET"):
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
    # try:
    msg = request.get_json()
    # Create or update state of current camera
    state = msg["state"]
    # print(state)
    # check if the device exists.
    if dbase.is_device(cur, state["device_uuid"]):
        dbase.update_device(
            cur, state["device_uuid"], states[state["status"]], state["req_time"]
        )
    else:
        dbase.insert_device(
            cur,
            state["device_uuid"],
            state["device_name"],
            states[state["status"]],
            state["req_time"],
        )
        # also add a foreign server + table to the database
        dbase.create_foreign_table(cur, state["device_uuid"])

    log_msg = f'Cam {state["device_uuid"]} on {state["ip"]} - {method} {msg["req"]}'
    logger.debug(log_msg)
    # check if task exists and sent instructions back
    func = f'{method.lower()}_{msg["req"].lower()}'
    if not (hasattr(camrig, func)):
        return "method not available", 404
    if "kwargs" in msg:
        kwargs = msg["kwargs"]
    else:
        kwargs = {}
    req = getattr(camrig, func)
    # execute with key-word arguments provided
    r = req(cur, state, **kwargs)

    return r, 200
    # except:
    #     return 'method failed', 500


def get_online(cur, state):
    """
    :return:
    dict representation of the root folder
    """
    # cur_project = dbase.query_project_active(cur, as_dict=True)
    # # retrieve project with project_id
    # if len(cur_project) == 0:
    logger.info(f"Cam {state['device_uuid']} is now online")
    return {"task": "wait", "kwargs": {}}

    # project = dbase.query_projects(
    #     cur, project_id=cur_project["project_id"], as_dict=True, flatten=True
    # )
    # return {"project": project}


def get_task(cur, state):
    """
    Choose a task for the child to perform, and return this
    Currently implemented are:
        init: - initialize camera (done when status of camera is 'idle')
        wait: - tell camera to simply wait and send a request for a task later (typically done when not all cameras are online yet
        capture_until: - capture until a stop (not implemented yet) is given, using kwargs for time and time intervals
                         this is only provided when all cameras in the expected camera rig size are initialized
    :return:
    dict representation of task, including the following fields:
    task: str - name of task method to be performed on child side
    kwargs: dict - set of key word arguments and their values to provide to that task
    """
    rig = dbase.query_project_active(cur, as_dict=True)
    cur_device = dbase.query_devices(
        cur, device_uuid=state["device_uuid"], as_dict=True, flatten=True
    )
    # get states of parent and child in human readable format
    device_status = utils.get_key_state(cur_device["status"])
    if len(rig) > 0:
        rig_status = utils.get_key_state(rig["status"])
        if device_status != rig_status:
            # something needs to be done to get the states the same
            task_name = f"task_{device_status}_to_{rig_status}"
            if not (hasattr(camrig, task_name)):
                return f"task {task_name} not available"
            task = getattr(camrig, task_name)
            # execute task
            return task(cur, state)
            # camera is already capturing, so just wait for further instructions (stop)
    return {"task": "wait", "kwargs": {}}

def post_log(cur, state, msg, level="info"):
    """
    Log message from current camera on logger
    :return:
    dict {'success': False or True}
    """
    try:
        log_msg = f'Cam {state["device_uuid"]} - {msg}'
        log_method = getattr(logger, level)
        log_method(log_msg)
        return {"success": True}
    except:
        return {"success": False}

def task_idle_to_ready(cur, state):
    logger.info("Sending camera initialization ")
    return {"task": "init", "kwargs": {}}

def task_capture_to_ready(cur, state):
    return {"task": "stop", "kwargs": {}}


def task_ready_to_capture(cur, state):
    # retrieve settings of current project
    cur_project = dbase.query_project_active(cur, as_dict=True)
    project = dbase.query_projects(
        cur, project_id=cur_project["project_id"], as_dict=True, flatten=True
    )
    dt = int(project["dt"])

    cur_address = request.remote_addr  # TODO: also add uuid of device
    # check how many cams have the state 'ready', only start when the full rig is ready
    n_cams_ready = len(dbase.query_devices(cur, status=states["ready"]))

    # compute cams ready from a PostGreSQL query
    if n_cams_ready == project["n_cams"]:
        logger.info(
            f'All cameras ready. Start capturing on device {state["device_uuid"]} on ip {state["ip"]}'
        )
        # no start time has been set yet, ready to start the time
        logger.debug("All cameras are ready, setting start time")

        start_time_epoch = dt * round(
            (time.time() + 10) / dt
        )  # this number is send to the child to start capturing
        start_datetime = datetime.datetime.fromtimestamp(start_time_epoch)
        start_datetime_utc = utils.to_utc(start_datetime)
        survey_run = start_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")
        # set start time for capturing, and set state to capture
        dbase.update_project_active(
            cur, status=states["capture"], start_time=start_datetime_utc
        )
        # add survey_run to surveys table
        dbase.insert_survey(cur, project_id=cur_project["project_id"], survey_run=survey_run)
        logger.debug(
            f'start time is set to {start_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")}'
        )
        logger.info(f"Sending capture command to {cur_address}")
        return {
            "task": "capture_continuous",
            "kwargs": {
                "start_time": start_time_epoch,
                "survey_run": survey_run,
                "project": project,
            },
        }
    else:
        # this should not happen as the front end part already checks if enough cams are online.
        logger.info(
            f'Only {n_cams_ready} out of {project["n_cams"]} ready for capture, switching state back'
        )
        return {"task": "wait", "kwargs": {}}
        # roll back to state "ready"
        dbase.update_project_active(cur, status=states["ready"])

def task_ready_to_stream(cur, state):
    # retrieve settings of current project
    cur_project = dbase.query_project_active(cur, as_dict=True)
    project = dbase.query_projects(
        cur, project_id=cur_project["project_id"], as_dict=True, flatten=True
    )

    cur_address = request.remote_addr  # TODO: also add uuid of device
    # check how many cams have the state 'ready', only start when the full rig is ready
    n_cams_ready = len(dbase.query_devices(cur, status=states["ready"]))

    # compute cams ready from a PostGreSQL query
    if n_cams_ready == project["n_cams"]:
        logger.info(
            f'All cameras ready. Start streaming on device {state["device_uuid"]} on ip {state["ip"]}'
        )
        # set state to stream
        dbase.update_project_active(
            cur, status=states["stream"]
        )
        logger.info(f"Sending stream command to {cur_address}")
        return {
            "task": "capture_stream",
            "kwargs": {},
        }
    else:
        # this should not happen as the front end part already checks if enough cams are online.
        logger.info(
            f'Only {n_cams_ready} out of {project["n_cams"]} ready for capture, switching state back'
        )
        return {"task": "wait", "kwargs": {}}
        # roll back to state "ready"
        dbase.update_project_active(cur, status=states["ready"])

def task_stream_to_ready(cur, state):
    return {"task": "stop_stream", "kwargs": {}}
