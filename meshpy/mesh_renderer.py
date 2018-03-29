"""
Class to render a set of images for a graspable objects
Author: Jeff Mahler
"""
import copy
import IPython
import logging
import numpy as np
import os
import sys
import time

try:
    import meshrender
except:
    pass

from autolab_core import Point, RigidTransform
from autolab_core.utils import sph2cart, cart2sph
from perception import CameraIntrinsics, BinaryImage, ColorImage, DepthImage, RgbdImage, ObjectRender
from meshpy_berkeley import MaterialProperties, LightingProperties, RenderMode

class ViewsphereDiscretizer(object):
    """Set of parameters for automatically rendering a set of images from virtual
    cameras placed around a viewing sphere.

    The view sphere indicates camera poses relative to the object.

    Attributes
    ----------
    min_radius : float
        Minimum radius for viewing sphere.
    max_radius : float
        Maximum radius for viewing sphere.
    num_radii  : int
        Number of radii between min_radius and max_radius.
    min_elev : float
        Minimum elevation (angle from z-axis) for camera position.
    max_elev : float
        Maximum elevation for camera position.
    num_elev  : int
        Number of discrete elevations.
    min_az : float
        Minimum azimuth (angle from x-axis) for camera position.
    max_az : float
        Maximum azimuth for camera position.
    num_az  : int
        Number of discrete azimuth locations.
    min_roll : float
        Minimum roll (rotation of camera about axis generated by azimuth and
        elevation) for camera.
    max_roll : float
        Maximum roll for camera.
    num_roll  : int
        Number of discrete rolls.
    """

    def __init__(self, min_radius, max_radius, num_radii,
                 min_elev, max_elev, num_elev,
                 min_az=0, max_az=2*np.pi, num_az=1,
                 min_roll=0, max_roll=2*np.pi, num_roll=1):
        """Initialize a ViewsphereDiscretizer.

        Parameters
        ----------
        min_radius : float
            Minimum radius for viewing sphere.
        max_radius : float
            Maximum radius for viewing sphere.
        num_radii  : int
            Number of radii between min_radius and max_radius.
        min_elev : float
            Minimum elevation (angle from z-axis) for camera position.
        max_elev : float
            Maximum elevation for camera position.
        num_elev  : int
            Number of discrete elevations.
        min_az : float
            Minimum azimuth (angle from x-axis) for camera position.
        max_az : float
            Maximum azimuth for camera position.
        num_az  : int
            Number of discrete azimuth locations.
        min_roll : float
            Minimum roll (rotation of camera about axis generated by azimuth and
            elevation) for camera.
        max_roll : float
            Maximum roll for camera.
        num_roll  : int
            Number of discrete rolls.
        """
        if num_radii < 1 or num_az < 1 or num_elev < 1:
            raise ValueError('Discretization must be at least one in each dimension')
        self.min_radius = min_radius
        self.max_radius = max_radius
        self.num_radii = num_radii
        self.min_az = min_az
        self.max_az = max_az
        self.num_az = num_az
        self.min_elev = min_elev
        self.max_elev = max_elev
        self.num_elev = num_elev
        self.min_roll = min_roll
        self.max_roll = max_roll
        self.num_roll = num_roll

    def object_to_camera_poses(self):
        """Turn the params into a set of object to camera transformations.

        Returns
        -------
        :obj:`list` of :obj:`RigidTransform`
            A list of rigid transformations that transform from object space
            to camera space.
        """
        # compute increments in radial coordinates
        if self.max_radius == self.min_radius:
            radius_inc = 1
        elif self.num_radii == 1:
            radius_inc = self.max_radius - self.min_radius + 1
        else:
            radius_inc = (self.max_radius - self.min_radius) / (self.num_radii - 1)
        az_inc = (self.max_az - self.min_az) / self.num_az
        if self.max_elev == self.min_elev:
            elev_inc = 1
        elif self.num_elev == 1:
            elev_inc = self.max_elev - self.min_elev + 1
        else:
            elev_inc = (self.max_elev - self.min_elev) / (self.num_elev - 1)
        roll_inc = (self.max_roll - self.min_roll) / self.num_roll

        # create a pose for each set of spherical coords
        object_to_camera_poses = []
        radius = self.min_radius
        while radius <= self.max_radius:
            elev = self.min_elev
            while elev <= self.max_elev:
                az = self.min_az
                while az < self.max_az: #not inclusive due to topology (simplifies things)
                    roll = self.min_roll
                    while roll < self.max_roll:

                        # generate camera center from spherical coords
                        camera_center_obj = np.array([sph2cart(radius, az, elev)]).squeeze()
                        camera_z_obj = -camera_center_obj / np.linalg.norm(camera_center_obj)

                        # find the canonical camera x and y axes
                        camera_x_par_obj = np.array([camera_z_obj[1], -camera_z_obj[0], 0])
                        if np.linalg.norm(camera_x_par_obj) == 0:
                            camera_x_par_obj = np.array([1, 0, 0])
                        camera_x_par_obj = camera_x_par_obj / np.linalg.norm(camera_x_par_obj)
                        camera_y_par_obj = np.cross(camera_z_obj, camera_x_par_obj)
                        camera_y_par_obj = camera_y_par_obj / np.linalg.norm(camera_y_par_obj)
                        if camera_y_par_obj[2] > 0:
                            camera_x_par_obj = -camera_x_par_obj
                            camera_y_par_obj = np.cross(camera_z_obj, camera_x_par_obj)
                            camera_y_par_obj = camera_y_par_obj / np.linalg.norm(camera_y_par_obj)

                        # rotate by the roll
                        R_obj_camera_par = np.c_[camera_x_par_obj, camera_y_par_obj, camera_z_obj]
                        R_camera_par_camera = np.array([[np.cos(roll), -np.sin(roll), 0],
                                                        [np.sin(roll), np.cos(roll), 0],
                                                        [0, 0, 1]])
                        R_obj_camera = R_obj_camera_par.dot(R_camera_par_camera)
                        t_obj_camera = camera_center_obj

                        # create final transform
                        T_obj_camera = RigidTransform(R_obj_camera, t_obj_camera,
                                                      from_frame='camera', to_frame='obj')
                        object_to_camera_poses.append(T_obj_camera.inverse())
                        roll += roll_inc
                    az += az_inc
                elev += elev_inc
            radius += radius_inc
        return object_to_camera_poses

class PlanarWorksurfaceDiscretizer(object):
    """
    Set of parameters for automatically rendering a set of images from virtual
    cameras placed around a viewsphere and translated along a planar worksurface.

    The view sphere indicates camera poses relative to the object.
    """
    def __init__(self, min_radius, max_radius, num_radii,
                 min_elev, max_elev, num_elev,
                 min_az=0, max_az=2*np.pi, num_az=1,
                 min_roll=0, max_roll=2*np.pi, num_roll=1,
                 min_x=0, max_x=1, num_x=1,
                 min_y=0, max_y=1, num_y=1):
        """Initialize a ViewsphereDiscretizer.

        Parameters
        ----------
        min_radius : float
            Minimum radius for viewing sphere.
        max_radius : float
            Maximum radius for viewing sphere.
        num_radii  : int
            Number of radii between min_radius and max_radius.
        min_elev : float
            Minimum elevation (angle from z-axis) for camera position.
        max_elev : float
            Maximum elevation for camera position.
        num_elev  : int
            Number of discrete elevations.
        min_az : float
            Minimum azimuth (angle from x-axis) for camera position.
        max_az : float
            Maximum azimuth for camera position.
        num_az  : int
            Number of discrete azimuth locations.
        min_roll : float
            Minimum roll (rotation of camera about axis generated by azimuth and
            elevation) for camera.
        max_roll : float
            Maximum roll for camera.
        num_roll  : int
            Number of discrete rolls.
        min_x : float
            Minimum x value.
        max_x : float
            Maximum x value.
        num_x  : int
            Number of points along x axis.
        min_y : float
            Minimum y value.
        may_y : float
            Mayimum y value.
        num_y  : int
            Number of points along y axis.
        """
        if num_radii < 1 or num_az < 1 or num_elev < 1:
            raise ValueError('Discretization must be at least one in each dimension')
        self.min_radius = min_radius
        self.max_radius = max_radius
        self.num_radii = num_radii
        self.min_az = min_az
        self.max_az = max_az
        self.num_az = num_az
        self.min_elev = min_elev
        self.max_elev = max_elev
        self.num_elev = num_elev
        self.min_roll = min_roll
        self.max_roll = max_roll
        self.num_roll = num_roll
        self.min_x = min_x
        self.max_x = max_x
        self.num_x = num_x
        self.min_y = min_y
        self.max_y = max_y
        self.num_y = num_y

    def object_to_camera_poses(self, camera_intr):
        """Turn the params into a set of object to camera transformations.

        Returns
        -------
        :obj:`list` of :obj:`RigidTransform`
            A list of rigid transformations that transform from object space
            to camera space.
        :obj:`list` of :obj:`RigidTransform`
            A list of rigid transformations that transform from object space
            to camera space without the translation in the plane
        :obj:`list` of :obj:`CameraIntrinsics`
            A list of camera intrinsics that project the translated object
            into the center pixel of the camera, simulating cropping
        """
        # compute increments in radial coordinates
        if self.max_radius == self.min_radius:
            radius_inc = 1
        elif self.num_radii == 1:
            radius_inc = self.max_radius - self.min_radius + 1
        else:
            radius_inc = (self.max_radius - self.min_radius) / (self.num_radii - 1)
        az_inc = (self.max_az - self.min_az) / self.num_az
        if self.max_elev == self.min_elev:
            elev_inc = 1
        elif self.num_elev == 1:
            elev_inc = self.max_elev - self.min_elev + 1
        else:
            elev_inc = (self.max_elev - self.min_elev) / (self.num_elev - 1)
        roll_inc = (self.max_roll - self.min_roll) / self.num_roll

        if self.max_x == self.min_x:
            x_inc = 1
        elif self.num_x == 1:
            x_inc = self.max_x - self.min_x + 1
        else:
            x_inc = (self.max_x - self.min_x) / (self.num_x - 1)


        if self.max_y == self.min_y:
            y_inc = 1
        elif self.num_y == 1:
            y_inc = self.max_y - self.min_y + 1
        else:
            y_inc = (self.max_y - self.min_y) / (self.num_y - 1)

        # create a pose for each set of spherical coords
        object_to_camera_poses = []
        object_to_camera_normalized_poses = []
        camera_shifted_intrinsics = []
        radius = self.min_radius
        while radius <= self.max_radius:
            elev = self.min_elev
            while elev <= self.max_elev:
                az = self.min_az
                while az < self.max_az: #not inclusive due to topology (simplifies things)
                    roll = self.min_roll
                    while roll < self.max_roll:
                        x = self.min_x
                        while x <= self.max_x:
                            y = self.min_y
                            while y <= self.max_y:
                                num_poses = len(object_to_camera_poses)

                                # generate camera center from spherical coords
                                delta_t = np.array([x, y, 0])
                                camera_center_obj = np.array([sph2cart(radius, az, elev)]).squeeze() + delta_t
                                camera_z_obj = -np.array([sph2cart(radius, az, elev)]).squeeze()
                                camera_z_obj = camera_z_obj / np.linalg.norm(camera_z_obj)

                                # find the canonical camera x and y axes
                                camera_x_par_obj = np.array([camera_z_obj[1], -camera_z_obj[0], 0])
                                if np.linalg.norm(camera_x_par_obj) == 0:
                                    camera_x_par_obj = np.array([1, 0, 0])
                                camera_x_par_obj = camera_x_par_obj / np.linalg.norm(camera_x_par_obj)
                                camera_y_par_obj = np.cross(camera_z_obj, camera_x_par_obj)
                                camera_y_par_obj = camera_y_par_obj / np.linalg.norm(camera_y_par_obj)
                                if camera_y_par_obj[2] > 0:
                                    print 'Flipping', num_poses
                                    camera_x_par_obj = -camera_x_par_obj
                                    camera_y_par_obj = np.cross(camera_z_obj, camera_x_par_obj)
                                    camera_y_par_obj = camera_y_par_obj / np.linalg.norm(camera_y_par_obj)

                                # rotate by the roll
                                R_obj_camera_par = np.c_[camera_x_par_obj, camera_y_par_obj, camera_z_obj]
                                R_camera_par_camera = np.array([[np.cos(roll), -np.sin(roll), 0],
                                                                [np.sin(roll), np.cos(roll), 0],
                                                                [0, 0, 1]])
                                R_obj_camera = R_obj_camera_par.dot(R_camera_par_camera)
                                t_obj_camera = camera_center_obj

                                # create final transform
                                T_obj_camera = RigidTransform(R_obj_camera, t_obj_camera,
                                                              from_frame='camera',
                                                              to_frame='obj')
                            
                                object_to_camera_poses.append(T_obj_camera.inverse())

                                # compute pose without the center offset because we can easily add in the object offset later
                                t_obj_camera_normalized = camera_center_obj - delta_t
                                T_obj_camera_normalized = RigidTransform(R_obj_camera, t_obj_camera_normalized,
                                                                         from_frame='camera',
                                                                         to_frame='obj')
                                object_to_camera_normalized_poses.append(T_obj_camera_normalized.inverse())

                                # compute new camera center by projecting object 0,0,0 into the camera
                                center_obj_obj = Point(np.zeros(3), frame='obj')
                                center_obj_camera = T_obj_camera.inverse() * center_obj_obj
                                u_center_obj = camera_intr.project(center_obj_camera)
                                camera_shifted_intr = copy.deepcopy(camera_intr)
                                camera_shifted_intr.cx = 2 * camera_intr.cx - float(u_center_obj.x)
                                camera_shifted_intr.cy = 2 * camera_intr.cy - float(u_center_obj.y)
                                camera_shifted_intrinsics.append(camera_shifted_intr)

                                y += y_inc
                            x += x_inc
                        roll += roll_inc
                    az += az_inc
                elev += elev_inc
            radius += radius_inc
        return object_to_camera_poses, object_to_camera_normalized_poses, camera_shifted_intrinsics

class SceneObject(object):
    """ Struct to encapsulate objects added to a scene """
    def __init__(self, mesh, T_mesh_world,
                 mat_props=MaterialProperties()):
        self.mesh = mesh
        self.T_mesh_world = T_mesh_world
        self.mat_props = mat_props

class VirtualCamera(object):
    """A virtualized camera for rendering virtual color and depth images of meshes.

    Rendering is performed by using OSMesa offscreen rendering and boost_numpy.
    """
    def __init__(self, camera_intr):
        """Initialize a virtual camera.

        Parameters
        ----------
        camera_intr : :obj:`CameraIntrinsics`
            The CameraIntrinsics object used to parametrize the virtual camera.

        Raises
        ------
        ValueError
            When camera_intr is not a CameraIntrinsics object.
        """
        if not isinstance(camera_intr, CameraIntrinsics):
            raise ValueError('Must provide camera intrinsics as a CameraIntrinsics object')
        self._camera_intr = camera_intr
        self._scene = {} 

    def add_to_scene(self, name, scene_object):
        """ Add an object to the scene.

        Parameters
        ---------
        name : :obj:`str`
            name of object in the scene
        scene_object : :obj:`SceneObject`
            object to add to the scene
        """
        self._scene[name] = scene_object

    def remove_from_scene(self, name):
        """ Remove an object to a from the scene.

        Parameters
        ---------
        name : :obj:`str`
            name of object to remove
        """
        self._scene[name] = None

    def images(self, mesh, object_to_camera_poses,
               mat_props=None, light_props=None, enable_lighting=True, debug=False):
        """Render images of the given mesh at the list of object to camera poses.

        Parameters
        ----------
        mesh : :obj:`Mesh3D`
            The mesh to be rendered.
        object_to_camera_poses : :obj:`list` of :obj:`RigidTransform`
            A list of object to camera transforms to render from.
        mat_props : :obj:`MaterialProperties`
            Material properties for the mesh
        light_props : :obj:`MaterialProperties`
            Lighting properties for the scene
        enable_lighting : bool
            Whether or not to enable lighting
        debug : bool
            Whether or not to debug the C++ meshrendering code.

        Returns
        -------
        :obj:`tuple` of `numpy.ndarray`
            A 2-tuple of ndarrays. The first, which represents the color image,
            contains ints (0 to 255) and is of shape (height, width, 3). 
            Each pixel is a 3-ndarray (red, green, blue) associated with a given
            y and x value. The second, which represents the depth image,
            contains floats and is of shape (height, width). Each pixel is a
            single float that represents the depth of the image.
        """
        # get mesh spec as numpy arrays
        vertex_arr = mesh.vertices
        tri_arr = mesh.triangles.astype(np.int32)
        if mesh.normals is None:
            mesh.compute_vertex_normals()
        norms_arr = mesh.normals

        # set default material properties
        if mat_props is None:
            mat_props = MaterialProperties()
        mat_props_arr = mat_props.arr

        # set default light properties
        if light_props is None:
            light_props = LightingProperties()

        # render for each object to camera pose
        # TODO: clean up interface, use modelview matrix!!!!
        color_ims = []
        depth_ims = []
        render_start = time.time()
        for T_obj_camera in object_to_camera_poses:
            # form projection matrix
            R = T_obj_camera.rotation
            t = T_obj_camera.translation
            P = self._camera_intr.proj_matrix.dot(np.c_[R, t])

            # form light props
            light_props.set_pose(T_obj_camera)
            light_props_arr = light_props.arr

            # render images for each
            c, d = meshrender.render_mesh([P],
                                          self._camera_intr.height,
                                          self._camera_intr.width,
                                          vertex_arr,
                                          tri_arr,
                                          norms_arr,
                                          mat_props_arr,
                                          light_props_arr,
                                          enable_lighting,
                                          debug)
            color_ims.extend(c)
            depth_ims.extend(d)
        render_stop = time.time()
        logging.debug('Rendering took %.3f sec' %(render_stop - render_start))

        return color_ims, depth_ims

    def images_viewsphere(self, mesh, vs_disc, mat_props=None, light_props=None):
        """Render images of the given mesh around a view sphere.

        Parameters
        ----------
        mesh : :obj:`Mesh3D`
            The mesh to be rendered.
        vs_disc : :obj:`ViewsphereDiscretizer`
            A discrete viewsphere from which we draw object to camera
            transforms.
        mat_props : :obj:`MaterialProperties`
            Material properties for the mesh
        light_props : :obj:`MaterialProperties`
            Lighting properties for the scene

        Returns
        -------
        :obj:`tuple` of `numpy.ndarray`
            A 2-tuple of ndarrays. The first, which represents the color image,
            contains ints (0 to 255) and is of shape (height, width, 3). 
            Each pixel is a 3-ndarray (red, green, blue) associated with a given
            y and x value. The second, which represents the depth image,
            contains floats and is of shape (height, width). Each pixel is a
            single float that represents the depth of the image.
        """
        return self.images(mesh, vs_disc.object_to_camera_poses(),
                           mat_props=mat_props, light_props=light_props)

    def wrapped_images(self, mesh, object_to_camera_poses,
                       render_mode, stable_pose=None, mat_props=None,
                       light_props=None,debug=False):
        """Create ObjectRender objects of the given mesh at the list of object to camera poses.

        Parameters
        ----------
        mesh : :obj:`Mesh3D`
            The mesh to be rendered.
        object_to_camera_poses : :obj:`list` of :obj:`RigidTransform`
            A list of object to camera transforms to render from.
        render_mode : int
            One of RenderMode.COLOR, RenderMode.DEPTH, or
            RenderMode.SCALED_DEPTH.
        stable_pose : :obj:`StablePose`
            A stable pose to render the object in.
        mat_props : :obj:`MaterialProperties`
            Material properties for the mesh
        light_props : :obj:`MaterialProperties`
            Lighting properties for the scene
        debug : bool
            Whether or not to debug the C++ meshrendering code.

        Returns
        -------
        :obj:`list` of :obj:`ObjectRender`
            A list of ObjectRender objects generated from the given parameters.
        """
        # pre-multiply the stable pose
        world_to_camera_poses = [T_obj_camera.as_frames('obj', 'camera') for T_obj_camera in object_to_camera_poses]
        if stable_pose is not None:
            t_obj_stp = np.array([0,0,-stable_pose.r.dot(stable_pose.x0)[2]])
            T_obj_stp = RigidTransform(rotation=stable_pose.r,
                                       translation=t_obj_stp,
                                       from_frame='obj',
                                       to_frame='stp')            
            stp_to_camera_poses = copy.copy(object_to_camera_poses)
            object_to_camera_poses = []
            for T_stp_camera in stp_to_camera_poses:
                T_stp_camera.from_frame = 'stp'
                object_to_camera_poses.append(T_stp_camera.dot(T_obj_stp))

        # set lighting mode
        enable_lighting = True
        if render_mode == RenderMode.SEGMASK or render_mode == RenderMode.DEPTH or \
           render_mode == RenderMode.DEPTH_SCENE:
            enable_lighting = False

        # render both image types (doesn't really cost any time)
        color_ims, depth_ims = self.images(mesh, object_to_camera_poses,
                                           mat_props=mat_props,
                                           light_props=light_props,
                                           enable_lighting=enable_lighting,
                                           debug=debug)

        # convert to image wrapper classes
        images = []
        if render_mode == RenderMode.SEGMASK:
            # wrap binary images
            for binary_im in color_ims:
                images.append(BinaryImage(binary_im[:,:,0], frame=self._camera_intr.frame, threshold=0))

        elif render_mode == RenderMode.COLOR:
            # wrap color images
            for color_im in color_ims:
                images.append(ColorImage(color_im, frame=self._camera_intr.frame))

        elif render_mode == RenderMode.COLOR_SCENE:
            # wrap color and depth images
            for color_im in color_ims:
                images.append(ColorImage(color_im, frame=self._camera_intr.frame))

            # render images of scene objects
            color_scene_ims = {}
            for name, scene_obj in self._scene.iteritems():
                scene_object_to_camera_poses = []
                for world_to_camera_pose in world_to_camera_poses:
                    scene_object_to_camera_poses.append(world_to_camera_pose * scene_obj.T_mesh_world)

                color_scene_ims[name] = self.wrapped_images(scene_obj.mesh, scene_object_to_camera_poses, RenderMode.COLOR, mat_props=scene_obj.mat_props, light_props=light_props, debug=debug)

            # combine with scene images
            # TODO: re-add farther
            for i in range(len(images)):
                for j, name in enumerate(color_scene_ims.keys()):
                    zero_px = images[i].zero_pixels()
                    images[i].data[zero_px[:,0], zero_px[:,1], :] = color_scene_ims[name][i].image.data[zero_px[:,0], zero_px[:,1], :]

        elif render_mode == RenderMode.DEPTH:
            # render depth image
            for depth_im in depth_ims:
                images.append(DepthImage(depth_im, frame=self._camera_intr.frame))

        elif render_mode == RenderMode.DEPTH_SCENE:
            # create empty depth images
            for depth_im in depth_ims:
                images.append(DepthImage(depth_im, frame=self._camera_intr.frame))

            # render images of scene objects
            depth_scene_ims = {}
            for name, scene_obj in self._scene.iteritems():
                scene_object_to_camera_poses = []
                for world_to_camera_pose in world_to_camera_poses:
                    scene_object_to_camera_poses.append(world_to_camera_pose * scene_obj.T_mesh_world)
                depth_scene_ims[name] = self.wrapped_images(scene_obj.mesh, scene_object_to_camera_poses, RenderMode.DEPTH, mat_props=scene_obj.mat_props, light_props=light_props)

            # combine with scene images
            for i in range(len(images)):
                for j, name in enumerate(depth_scene_ims.keys()):
                    images[i] = images[i].combine_with(depth_scene_ims[name][i].image)

        elif render_mode == RenderMode.RGBD:
            # create RGB-D images
            for color_im, depth_im in zip(color_ims, depth_ims):
                c = ColorImage(color_im, frame=self._camera_intr.frame)
                d = DepthImage(depth_im, frame=self._camera_intr.frame)
                images.append(RgbdImage.from_color_and_depth(c, d))

        elif render_mode == RenderMode.RGBD_SCENE:
            # create RGB-D images
            for color_im, depth_im in zip(color_ims, depth_ims):
                c = ColorImage(color_im, frame=self._camera_intr.frame)
                d = DepthImage(depth_im, frame=self._camera_intr.frame)
                images.append(RgbdImage.from_color_and_depth(c, d))

            # render images of scene objects
            rgbd_scene_ims = {}
            for name, scene_obj in self._scene.iteritems():
                scene_object_to_camera_poses = []
                for world_to_camera_pose in world_to_camera_poses:
                    scene_object_to_camera_poses.append(world_to_camera_pose * scene_obj.T_mesh_world)

                rgbd_scene_ims[name] = self.wrapped_images(scene_obj.mesh, scene_object_to_camera_poses, RenderMode.RGBD, mat_props=scene_obj.mat_props, light_props=light_props, debug=debug)

           # combine with scene images
            for i in range(len(images)):
                for j, name in enumerate(rgbd_scene_ims.keys()):
                    images[i] = images[i].combine_with(rgbd_scene_ims[name][i].image)

        elif render_mode == RenderMode.SCALED_DEPTH:
            # convert to color image
            for depth_im in depth_ims:
                d = DepthImage(depth_im, frame=self._camera_intr.frame)
                images.append(d.to_color())
        else:
            raise ValueError('Render mode %s not supported' %(render_mode))

        # create object renders
        if stable_pose is not None:
            object_to_camera_poses = copy.copy(stp_to_camera_poses)
        rendered_images = []
        for image, T_obj_camera in zip(images, object_to_camera_poses):
            T_camera_obj = T_obj_camera.inverse()
            rendered_images.append(ObjectRender(image, T_camera_obj))

        return rendered_images

    def wrapped_images_viewsphere(self, mesh, vs_disc, render_mode, stable_pose=None, mat_props=None, light_props=None):
        """Create ObjectRender objects of the given mesh around a viewsphere.

        Parameters
        ----------
        mesh : :obj:`Mesh3D`
            The mesh to be rendered.
        vs_disc : :obj:`ViewsphereDiscretizer`
            A discrete viewsphere from which we draw object to camera
            transforms.
        render_mode : int
            One of RenderMode.COLOR, RenderMode.DEPTH, or
            RenderMode.SCALED_DEPTH.
        stable_pose : :obj:`StablePose`
            A stable pose to render the object in.
        mat_props : :obj:`MaterialProperties`
            Material properties for the mesh
        light_props : :obj:`MaterialProperties`
            Lighting properties for the scene

        Returns
        -------
        :obj:`list` of :obj:`ObjectRender`
            A list of ObjectRender objects generated from the given parameters.
        """
        return self.wrapped_images(mesh, vs_disc.object_to_camera_poses(), render_mode, stable_pose=stable_pose, mat_props=mat_props, light_props=light_props)

    def wrapped_images_planar_worksurface(self, mesh, ws_disc, render_mode, stable_pose=None, mat_props=None, light_props=None):
        """ Create ObjectRender objects of the given mesh around a viewsphere and 
        a planar worksurface, where translated objects project into the center of
        the  camera.

        Parameters
        ----------
        mesh : :obj:`Mesh3D`
            The mesh to be rendered.
        ws_disc : :obj:`PlanarWorksurfaceDiscretizer`
            A discrete viewsphere and translations in plane from which we draw
            object to camera transforms.
        render_mode : int
            One of RenderMode.COLOR, RenderMode.DEPTH, or
            RenderMode.SCALED_DEPTH.
        stable_pose : :obj:`StablePose`
            A stable pose to render the object in.
        mat_props : :obj:`MaterialProperties`
            Material properties for the mesh
        light_props : :obj:`MaterialProperties`
            Lighting properties for the scene

        Returns
        -------
        :obj:`list` of :obj:`ObjectRender`
            A list of ObjectRender objects generated from the given parameters.
        :obj:`list` of :obj:`RigidTransform`
            A list of the transformations from object frame to camera frame used
            for rendering the images.
        :obj:`list` of :obj:`CameraIntrinsics`
            A list of the camera intrinsics used for rendering the images.
        """
        # save original intrinsics
        old_camera_intr = copy.deepcopy(self._camera_intr)
        object_to_camera_poses, object_to_camera_normalized_poses, shifted_camera_intrinsics = ws_disc.object_to_camera_poses(old_camera_intr)
        logging.info('Rendering %d images' %(len(object_to_camera_poses)))

        images = []
        for T_obj_camera, shifted_camera_intr in zip(object_to_camera_poses, shifted_camera_intrinsics):
            self._camera_intr = shifted_camera_intr
            images.extend(self.wrapped_images(mesh, [T_obj_camera], render_mode, stable_pose=stable_pose, mat_props=mat_props, light_props=light_props))

        self._camera_intr = old_camera_intr
        return images, object_to_camera_poses, shifted_camera_intrinsics
