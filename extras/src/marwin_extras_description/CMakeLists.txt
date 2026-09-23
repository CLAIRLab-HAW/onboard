cmake_minimum_required(VERSION 3.5)
project(marwin_extras_description)

find_package(ament_cmake REQUIRED)

# Data only -- no target is built here.
install(
  DIRECTORY urdf
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
