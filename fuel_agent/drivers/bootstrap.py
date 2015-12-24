# Copyright 2015 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from fuel_agent.drivers import nailgun
from fuel_agent.objects import base


class BootstrapBuildImage(nailgun.NailgunBuildImage):
    # TODO(fzhadaev): Drivers architecture should be refactored -
    #                 this driver shouldn't be inherited from NailgunBuildImage
    def __init__(self, data):
        super(BootstrapBuildImage, self).__init__(data)
        self.bootstrap_scheme = base.DictWrapperObject(data['bootstrap'])
        self.output = data['output']
