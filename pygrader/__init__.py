import argparse

import docker
import tarfile
import time
import os
import sys
from io import BytesIO

EXECUTION_PATH = "/tmp/grader"
SUPPORTED_LANGUAGES = ['py']
IMAGE_INFILE = "in.txt"
IMAGE_OUTFILE = "out.txt"


def add_to_tar(tar, image_filename, real_filename):
    tarinfo = tarfile.TarInfo(name=image_filename)
    tarinfo.size = os.stat(real_filename).st_size
    tarinfo.mtime = time.time()

    with open(real_filename, 'rb') as file:
        tar.addfile(tarinfo, file)


# TODO: timeout, memory limit, restrict internet access, prevent file access?


def grade(language, infile, outfile, codefile):
    # setup docker connection
    client = docker.from_env()

    # assemble tar archive with input file and script code file
    image_codefile = "script.{}".format(language)
    instream = BytesIO()
    tar = tarfile.TarFile(fileobj=instream, mode='w')
    add_to_tar(tar, IMAGE_INFILE, infile)
    add_to_tar(tar, image_codefile, codefile)
    tar.close()
    instream.seek(0)

    # create container
    container = client.containers.run(
        image={ 'py': 'python:3' }[language],
        command="""/bin/bash -c "while true; do sleep 30; done;" """,
        detach=True
    )

    # add tar archive into the container
    container.exec_run("mkdir {}".format(EXECUTION_PATH))
    container.put_archive(path=EXECUTION_PATH, data=instream)

    # execute the actual script
    if language == 'py':
        command = "python {}".format(image_codefile)
    print(container.exec_run("""/bin/bash -c "cd {}; {}" """.format(EXECUTION_PATH, command)))

    # # extract tar of script output
    out, _ = container.get_archive(os.path.join(EXECUTION_PATH, IMAGE_OUTFILE))
    outstream = BytesIO()
    for data in out:
        outstream.write(data)
    outstream.seek(0)
    tar = tarfile.TarFile(fileobj=outstream)

    user_out = tar.extractfile(IMAGE_OUTFILE).read()
    with open(outfile, 'rb') as correct_outfile:
        correct_out = correct_outfile.read()

    return user_out.strip() == correct_out.strip()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run a script inside of an isolated Docker environment.")
    parser.add_argument('language', choices=SUPPORTED_LANGUAGES, help="language of script")
    parser.add_argument('infile', help="path of input to script")
    parser.add_argument('outfile', help="path of correct output to script")
    parser.add_argument('codefile', help="path to script")

    args = parser.parse_args()
    if grade(**vars(args)):
        sys.exit(0)
    else:
        sys.exit(1)
