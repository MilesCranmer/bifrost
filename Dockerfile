FROM mcranmer/bifrost:gpu-base

MAINTAINER Ben Barsdell <benbarsdell@gmail.com>

# Build the library
WORKDIR /bifrost
RUN git clone https://github.com/ledatelescope/bifrost.git /bifrost && \
    make -j && \
    make install

ENV LD_LIBRARY_PATH /usr/local/lib:${LD_LIBRARY_PATH}

EXPOSE 8888

RUN ["/bin/bash"]
