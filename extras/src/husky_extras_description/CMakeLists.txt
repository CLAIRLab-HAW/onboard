cmake_minimum_required(VERSION 3.5)
project(husky_extras_description)

find_package(ament_cmake REQUIRED)

# Data only -- no target is built here.  The two directories have to land under share/ because everything that
# reads them does so through the ament index: the generator resolves the file through robot.yaml's absolute path,
# but RViz and the foxglove_bridge resolve package://husky_extras_description/meshes/... through THIS install.
install(
  DIRECTORY urdf meshes
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
