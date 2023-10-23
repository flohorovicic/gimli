import os.path
from glob import glob
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pygimli as pg
import pygimli.meshtools as mt
from pygimli.physics import ert
from .processing import combineMultipleData
from datetime import datetime, timedelta


# move general timelapse stuff to method-independent class
# class Timelapse():
#     mask
#     chooseTime
# class TimelapseERT(Timelapse)


class TimelapseERT():
    """Class for crosshole ERT data manipulation.

    Note that this class is to be split into a hierarchy of classes for general
    timelapse data management, timelapse ERT and crosshole ERT.
    You can load data, filter them data in the temporal or measuring axis, plot
    data, run inversion and export data and result files.

    """

    def __init__(self, filename=None, **kwargs):
        """Initialize class and possibly load data.

        Parameters
        ----------
        filename : str
            filename to load data, times, RHOA and ERR from
        data : DataContainerERT
            The data with quadrupoles for all
        times : np.array of datetime objects
            measuring times
        DATA : 2d np.array (data.size(), len(times))
            all apparent resistivities
        ERR : 2d np.array (data.size(), len(times))
            all apparent relative errors
        bhmap : array
            map electrode numbers to borehole numbers
        mesh : array
            mesh for inversion
        """
        self.data = kwargs.pop("data", None)
        self.DATA = kwargs.pop("DATA", [])
        self.ERR = kwargs.pop("ERR", [])
        self.times = kwargs.pop("times", [])
        self.mesh = kwargs.pop("mesh", None)
        self.models = []
        self.chi2s = []
        self.model = None
        self.mgr = ert.ERTManager()
        if filename is not None:
            self.load(filename, **kwargs)
        else:
            self.name = kwargs.pop("name", "new")

        if np.any(self.DATA):
            self.mask()

    def __repr__(self):  # for print function
        """Return string representation of the class."""
        out = ['Timelapse ERT data:', self.data.__str__()]
        if np.any(self.DATA):
            out.append("{} time steps".format(self.DATA.shape[1]))
            if np.any(self.times):
                out[-1] += " from " + self.times[0].isoformat(" ", "minutes")
                out[-1] += " to " + self.times[-1].isoformat(" ", "minutes")

        return "\n".join(out)

    def load(self, filename, **kwargs):
        """Load or import data."""  # TL-ERT
        if os.path.isfile(filename):
            self.data = ert.load(filename)
            if os.path.isfile(filename[:-4]+".rhoa"):
                self.DATA = np.loadtxt(filename[:-4]+".rhoa")
            if os.path.isfile(filename[:-4]+".err"):
                self.ERR = np.loadtxt(filename[:-4]+".err")
            if os.path.isfile(filename[:-4]+".times"):
                timestr = np.loadtxt(filename[:-4]+".times", dtype=str)
                self.times = np.array([datetime.fromisoformat(s) for s in timestr])
        elif "*" in filename:
            DATA = [ert.load(fname) for fname in glob(filename)]
            self.data, self.DATA, self.ERR = combineMultipleData(DATA)

        self.name = filename[:-4].replace("*", "All")
        nt = self.DATA.shape[1]
        if len(self.times) != nt:  # default: days from now
            self.times = datetime.now() + np.arange(nt) * timedelta(days=1)

    def saveData(self, filename=None):
        """Save all data as datacontainer, times, rhoa and error arrays."""
        filename = filename or self.name
        self.data.save(filename + ".shm")
        np.savetxt(filename+".rhoa", self.DATA, fmt="%6.2f")
        if np.any(self.ERR):
            np.savetxt(filename+".err", self.ERR, fmt="%6.2f")
        with open(filename+".times", "w", encoding="utf-8") as fid:
            for d in self.times:
                fid.write(d.isoformat()+"\n")
        self.name = filename

    def timeIndex(self, t):  #
        """Return index of closest timestep in times to t.

        Parameters
        ----------
        t : str|datetime
            datetime object or string
        """
        if isinstance(t, str):  # convert into datetime
            t = datetime.fromisoformat(t) # check others
        if isinstance(t, datetime): # detect closest point
            return np.argmin(np.abs(self.times-t))
        elif isinstance(t, (int, np.int32)):
            return t
        elif hasattr(t, "__iter__"):
            return np.array([self.timeIndex(ti) for ti in t], dtype=int)
        else:
            raise TypeError("Unknown type", type(t))

    def filter(self, tmin=0, tmax=None, t=None, select=None, kmax=None):
        """Filter data set temporally or data-wise.

        Parameters
        ----------
        tmin, tmax : int|str|datetime
            minimum and maximum times to keep
        t : int|str|datetime
            time to remove
        kmax : float
            maximum geometric factor to allow
        """
        if np.any(self.DATA):
            if select is not None:
                ind = self.timeIndex(select)
            else:
                tmin = self.timeIndex(tmin)  # converts dt/str to int
                if tmax is None:
                    tmax = self.DATA.shape[1]
                else:
                    tmax = self.timeIndex(tmax)

                ind = np.arange(tmin, tmax)
                if t is not None:
                    ind = np.setxor1d(ind, t)

            self.DATA = self.DATA[:, ind]
            if np.any(self.ERR):
                self.ERR = self.ERR[:, ind]
            if np.any(self.times):
                self.times = self.times[ind]
        if kmax is not None:
            ind = np.nonzero(np.abs(self.data["k"]) < kmax)[0]
            self.data["valid"] = 0
            self.data.markValid(ind)
            self.data.removeInvalid()
            if np.any(self.DATA):
                self.DATA = self.DATA[ind, :]
            if np.any(self.ERR):
                self.ERR = self.ERR[ind, :]

    def mask(self, rmin=0.1, rmax=1e6, emax=None):
        """Mask data.

        Parameters
        ----------
        rmin, rmax : float
            minimum and maximum apparent resistivity
        emax : float
            maximum error
        """
        self.DATA = np.ma.masked_invalid(self.DATA)
        self.DATA = np.ma.masked_outside(self.DATA, rmin, rmax)
        if emax is not None:
            self.DATA.mask = np.bitwise_or(self.DATA.mask, self.ERR > emax)

    def showData(self, v="rhoa", x="a", y="m", t=None, **kwargs):
        """Show data.

        Show data as pseudosections (single-hole) or cross-plot (crosshole)

        Parameters
        ----------
        v : str|array ["rhoa]
            array or field to plot
        x, y : str|array ["a", "m"]
            values to use for x and y axes
        t : int|str|datetime
            time to choose
        kwargs : dict
            forwarded to ert.show or showDataContainerAsMatrix
        """
        kwargs.setdefault("cMap", "Spectral_r")
        if t is not None:
            t = self.timeIndex(t)
            rhoa = self.DATA[:, t]
            v = rhoa.data
            v[rhoa.mask] = np.nan
        if 0:  # 3D case to be
            return pg.viewer.mpl.showDataContainerAsMatrix(
                self.data, x, y, v, **kwargs)
        else:
            return self.data.show(v, **kwargs)

    def showTimeline(self, ax=None, **kwargs):
        """Show data timeline.

        Parameters
        ----------
        ax : mpl.Axes|None
            matplotlib axes to plot (otherwise new)
        a, b, m, n : int
            tokens to extract data from
        """
        if ax is None:
            _, ax = plt.subplots(figsize=[8, 5])
        good = np.ones(self.data.size(), dtype=bool)
        lab = kwargs.pop("label", "ABMN") + ": "
        for k, v in kwargs.items():
            good = np.bitwise_and(good, self.data[k] == v)

        abmn = [self.data[tok] for tok in "abmn"]
        for i in np.nonzero(good)[0]:
            lab1 = lab + " ".join([str(tt[i]) for tt in abmn])
            ax.semilogy(self.times, self.DATA[i, :], "x-", label=lab1)

        ax.grid(True)
        ax.legend()
        ax.set_xlabel("time")
        ax.set_ylabel("resistivity (Ohmm)")
        return ax

    def generateDataPDF(self, **kwargs):
        """Generate a pdf with all data as timesteps in individual pages.

        Iterates through times and calls showData into multi-page pdf
        """
        kwargs.setdefault("verbose", False)
        with PdfPages(self.name+'-data.pdf') as pdf:
            fig = plt.figure(figsize=kwargs.pop("figsize", [5, 5]))
            for i in range(self.DATA.shape[1]):
                ax = fig.subplots()
                self.showData(t=i, ax=ax, **kwargs)
                ax.set_title(str(i)+": "+ self.times[i].isoformat(" ", "minutes"))
                fig.savefig(pdf, format='pdf')
                fig.clf()

    def chooseTime(self, t=None, **kwargs):
        """Return data for specific time.

        Parameters
        ----------
        t : int|str|datetime
        """
        if not isinstance(t, int):
            t = self.timeIndex(t)

        rhoa = self.DATA[:, t].copy()
        arhoa = np.abs(rhoa.data)
        arhoa[rhoa.mask] = np.nanmedian(arhoa)
        data = self.data.copy()
        data["rhoa"] = arhoa
        data.estimateError()
        data["err"][rhoa.mask] = 1e8
        self.data = data
        return data

    def createMesh(self, **kwargs):
        """Generate inversion mesh."""
        self.mesh = ert.createInversionMesh(self.data, **kwargs)
        self.mgr.setMesh(mesh=self.mesh)
        if kwargs.pop("show", False):
            print(self.mesh)
            pg.show(self.mesh, markers=True, showMesh=True)

    def invert(self, t=None, reg={}, **kwargs):
        """Run inversion for a specific timestep or all subsequently."""
        if t is not None:
            t = self.timeIndex(t)

        if self.mesh is None:
            self.createMesh()
        self.mgr.fop.setVerbose(False)
        if isinstance(reg, dict):
            self.mgr.inv.setRegularization(**reg)
        if t is None:  # all
            t = np.arange(len(self.times))

        t = np.atleast_1d(t)
        self.models = []
        self.chi2s = []
        startModel = kwargs.pop("startModel", 100)
        creep = kwargs.pop("creep", False)
        for i, ti in enumerate(np.atleast_1d(t)):
            self.mgr.setData(self.chooseTime(ti))
            self.model = self.mgr.invert(startModel=startModel, **kwargs)
            if i == 0 or creep:
                startModel = self.model.copy()

            self.models.append(self.model)
            self.chi2s.append(self.mgr.inv.chi2())

        if len(t) == 1:
            self.mgr.showResult()

        self.pd = self.mgr.paraDomain

    def fullInversion(self, scalef=1.0, **kwargs):
        """Full (4D) inversion."""
        DATA = [self.chooseTime(ti) for ti in range(len(self.times))]
        fop = pg.frameworks.MultiFrameModelling(ert.ERTModelling, scalef=scalef)
        fop.setData(DATA)
        if self.mesh is None:
            self.createMesh()

        fop.setMesh(self.mesh)
        print(fop.mesh())  # important to call mesh() function once!
        dataVec = np.concatenate([data["rhoa"] for data in DATA])
        errorVec = np.concatenate([data["err"] for data in DATA])
        startModel = fop.createStartModel(dataVec)
        inv = pg.Inversion(fop=fop, startModel=startModel, verbose=True)
        fop.createConstraints()
        kwargs.setdefault("maxIter", 10)
        kwargs.setdefault("verbose", True)
        kwargs.setdefault("startModel", startModel)
        model = inv.run(dataVec, errorVec, **kwargs)
        self.models = np.reshape(model, [len(DATA), -1])
        self.pd = fop.paraDomain
        return model

    def showFit(self, **kwargs):
        """Show data, model response and misfit."""
        _, ax = plt.subplots(nrows=3, figsize=(10, 6), sharex=True, sharey=True)
        _, cb = self.showData(ax=ax[0], verbose=False)
        self.showData(self.mgr.inv.response, ax=ax[1],
                      cMin=cb.vmin, cMax=cb.vmax, verbose=False)
        misfit = self.mgr.inv.response / self.data["rhoa"] * 100 - 100
        self.showData(misfit, ax=ax[2], cMin=-10, cMax=10, cMap="bwr", verbose=0)
        return ax

    def generateModelPDF(self, **kwargs):
        """Generate a multi-page pdf with the model results."""
        kwargs.setdefault('label', pg.unit('res'))
        kwargs.setdefault('cMap', pg.utils.cMap('res'))
        kwargs.setdefault('logScale', True)
        with PdfPages(self.name+'-model.pdf') as pdf:
            fig = plt.figure(figsize=kwargs.pop("figsize", [8, 5]))
            for i, model in enumerate(self.models):
                ax = fig.subplots()
                pg.show(self.pd, model, ax=ax, **kwargs)
                ax.set_title(str(i)+": " + self.times[i].isoformat(" ", "minutes"))
                fig.savefig(pdf, format='pdf')
                fig.clf()

    def generateRatioPDF(self, **kwargs):
        """Generate a multi-page pdf with the model results."""
        kwargs.setdefault('label', 'ratio')
        kwargs.setdefault('cMap', 'bwr')
        kwargs.setdefault('logScale', True)
        kwargs.setdefault("cMax", 2.0)
        kwargs.setdefault("cMin", 1/kwargs["cMax"])
        basemodel = self.models[0]
        with PdfPages(self.name+'-ratio.pdf') as pdf:
            fig = plt.figure(figsize=kwargs.pop("figsize", [8, 5]))
            for i, model in enumerate(self.models[1:]):
                ax = fig.subplots()
                pg.show(self.pd, model[i+1]/basemodel, ax=ax, **kwargs)
                ax.set_title(str(i)+": " + self.times[i+1].isoformat(" ", "minutes"))
                fig.savefig(pdf, format='pdf')
                fig.clf()


if __name__ == "__main__":
    pass
