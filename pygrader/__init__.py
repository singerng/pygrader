import argparse
from threading import Thread, Lock

import docker
import tarfile
import time
import os
import sys
import json
from io import BytesIO

EXECUTION_PATH = "/tmp/grader"
SUPPORTED_LANGUAGES = ['py']
TIMEOUT_WAIT = .050


def add_to_tar(tar, image_filename, real_filename):
    tarinfo = tarfile.TarInfo(name=image_filename)
    tarinfo.size = os.stat(real_filename).st_size
    tarinfo.mtime = time.time()

    with open(real_filename, 'rb') as file:
        tar.addfile(tarinfo, file)


# TODO: timeout, memory limit, restrict internet access, prevent file access?


def grade(problem_name, language, infile, outfile, codefile,
          timeout=2):
    # setup docker connection
    client = docker.from_env()

    # keep track of the status of grading throughout the program
    status = {'correct': True, 'message': "Correct"}

    # names of our three files within the docker container
    image_infile = "{}.in.txt".format(problem_name)
    image_outfile = "{}.out.txt".format(problem_name)
    image_codefile = "{}.{}".format(problem_name, language)

    # assemble tar archive with input file and script code file
    instream = BytesIO()
    tar = tarfile.TarFile(fileobj=instream, mode='w')
    add_to_tar(tar, image_infile, infile)
    add_to_tar(tar, image_codefile, codefile)
    tar.close()

    # now jump to the beginning of the stream we just wrote the tarfile to
    instream.seek(0)

    # create container and start it running
    # right now, it will run indefinitely
    container = client.containers.run(
        image={'py': 'python:3'}[language],
        command="""/bin/bash -c "while true; do sleep 30; done;" """,
        detach=True
    )

    # add tar archive into the container
    container.exec_run("mkdir {}".format(EXECUTION_PATH))
    container.put_archive(path=EXECUTION_PATH, data=instream)

    # execute the actual script
    if language == 'py':
        command = "python {}".format(image_codefile)

    # start getting setup for invoking the actual script
    # we'll start a new thread that will interrupt the docker container if necessary after some timeout
    # we lock it to be safe and keep track of the status of the container in the 'waiting' variable
    # since docker has no good way to check it
    status['threading'] = 'waiting'
    lock = Lock()

    def wait_for_timeout():
        # wait for the timeout, pausing occasionally to check whether the program has in fact completed
        # in which case this thread can exit
        while time.time() - start_time < timeout:
            time.sleep(TIMEOUT_WAIT)
            if status['threading'] == 'completed':
                return

        # search through all the running processes on the container and check whether our invocatino is still running
        # this is just to be safe
        running = False
        for process in container.top()['Processes']:
            if process[-1].endswith(command):
                running = True

        if running:
            # if the program is still going, kill the container, which interrupts our other code
            # and remember that we killed it
            lock.acquire()
            status['threading'] = 'killed'
            container.kill()
            lock.release()

    # start a separate thread to do the waiting
    waiting_thread = Thread(target=wait_for_timeout)
    waiting_thread.start()

    # run the actual script that was uploaded
    # this line is interrupted if it times out by the above thread
    start_time = time.time()
    exit_code, _ = container.exec_run("""/bin/bash -c "cd {}; {}" """.format(EXECUTION_PATH, command))
    end_time = time.time()

    # if it wasn't interrupted, then the status will still be 'waiting'
    # kill it; it'll still be running because of the original sleep invocation
    lock.acquire()
    if status['threading'] == 'waiting':
        container.kill()
        status['threading'] = 'completed'
    lock.release()

    # check if the thread was killed, and if so, mark it as a TLE
    if status['threading'] == 'killed' or end_time - start_time > timeout:
        status['correct'] = False
        status['message'] = "Time limit exceeded"
        status['time'] = -1
    else:
        status['time'] = end_time - start_time

    # check if the thread exited with an error, and if so, mark it as a runtime error
    if exit_code != 0 and status['correct']:
        status['correct'] = False
        status['message'] = "Runtime error"

    # only do this if we still think it might be correct
    if status['correct']:
        # extract tar of script output
        out, _ = container.get_archive(os.path.join(EXECUTION_PATH, image_outfile))
        outstream = BytesIO()
        for data in out:
            outstream.write(data)
        outstream.seek(0)
        tar = tarfile.TarFile(fileobj=outstream)

        # load the user program's output and the correct output
        user_out = tar.extractfile(image_outfile).read()
        with open(outfile, 'rb') as correct_outfile:
            correct_out = correct_outfile.read()

        # compare the two results
        status['correct'] = user_out.strip() == correct_out.strip()
        if not status['correct']:
            status['message'] = "Incorrect"

    return status


if __name__ == '__main__':
    # parse command line arguments
    parser = argparse.ArgumentParser(description="Run a script inside of an isolated Docker environment.")
    parser.add_argument('problem_name', help="problem name")
    parser.add_argument('language', choices=SUPPORTED_LANGUAGES, help="language of script")
    parser.add_argument('infile', help="path of input to script")
    parser.add_argument('outfile', help="path of correct output to script")
    parser.add_argument('codefile', help="path to script")

    args = parser.parse_args()
    status = grade(**vars(args))
    print(json.dumps(status))
    sys.stdout.flush()
    if status['correct']:
        sys.exit(0)
    else:
        sys.exit(1)
