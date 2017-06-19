FROM ubuntu:14.04

MAINTAINER Ben Barsdell <benbarsdell@gmail.com>

ARG DEBIAN_FRONTEND=noninteractive

# Get dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        pkg-config \
        software-properties-common \
        python \
        python-dev \
        exuberant-ctags \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fSsL -O https://bootstrap.pypa.io/get-pip.py && \
    python get-pip.py && \
    rm get-pip.py && \
    pip --no-cache-dir install \
        setuptools \
        numpy \
        matplotlib \
        contextlib2 \
        simplejson \
        pint \
        graphviz \
        git+https://github.com/MatthieuDartiailh/pyclibrary.git

ENV TERM xterm

# IPython
EXPOSE 8888

RUN ["/bin/bash"]