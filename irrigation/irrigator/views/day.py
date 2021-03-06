# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, division, unicode_literals
##
##  This file is part of MoaT, the Master of all Things.
##
##  MoaT is Copyright © 2007-2016 by Matthias Urlichs <matthias@urlichs.de>,
##  it is licensed under the GPLv3. See the file `README.rst` for details,
##  including optimistic statements by the author.
##
##  This program is free software: you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation, either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License (included; see the file LICENSE)
##  for more details.
##
##  This header is auto-generated and may self-destruct at any time,
##  courtesy of "make update". The original is in ‘scripts/_boilerplate.py’.
##  Thus, do not remove the next line, or insert any blank lines above.
##BP

from django.views.generic import ListView,DetailView,CreateView,UpdateView,DeleteView
from django.forms import ModelForm
from django.utils.translation import ugettext_lazy as _
from rainman.models import Day
from rainman.utils import get_request
from datetime import time
from irrigator.views import NonNegativeFloatField,TimeDeltaField,FormMixin,DbModelForm

class DayForm(ModelForm):
	class Meta:
		model = Day
		fields = "__all__"
	
class DayMixin(FormMixin):
	model = Day
	context_object_name = "day"

class DaysView(DayMixin,ListView):
	context_object_name = "day_list"

class DayView(DayMixin,DetailView):
	pass

class DayNewView(DayMixin,CreateView):
	form_class = DayForm
	success_url="/day/%(id)s"

class DayEditView(DayMixin,UpdateView):
	form_class = DayForm
	success_url="/day/%(id)s"

class DayDeleteView(DayMixin,DeleteView):
	success_url="/day/"

