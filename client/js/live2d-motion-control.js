/* Expose the bundled model's stable motion manager without editing vendor code. */
(function () {
  "use strict";

  const originalJsonp = window.webpackJsonpL2Dwidget;
  if (typeof originalJsonp !== "function" || !window.L2Dwidget) return;

  let currentModel = null;
  window.webpackJsonpL2Dwidget = function (chunkIds, modules) {
    const managerFactory = modules && modules[84];
    if (typeof managerFactory === "function" && !managerFactory.__desktopAvatarWrapped) {
      const wrappedFactory = function (module, exports, webpackRequire) {
        managerFactory(module, exports, webpackRequire);
        const Manager = exports && exports.cManager;
        const prototype = Manager && Manager.prototype;
        if (!prototype || prototype.__desktopAvatarWrapped) return;
        const createModel = prototype.createModel;
        prototype.createModel = function () {
          currentModel = createModel.apply(this, arguments);
          return currentModel;
        };
        prototype.__desktopAvatarWrapped = true;
      };
      wrappedFactory.__desktopAvatarWrapped = true;
      modules[84] = wrappedFactory;
    }
    return originalJsonp.apply(this, arguments);
  };

  function readyModel() {
    return currentModel
      && currentModel.initialized
      && currentModel.modelSetting
      && typeof currentModel.startMotion === "function"
      ? currentModel
      : null;
  }

  function muteMotionSounds(model) {
    const groups = model.modelSetting.json && model.modelSetting.json.motions;
    if (!groups || typeof groups !== "object") return;
    Object.keys(groups).forEach((group) => {
      const motions = Array.isArray(groups[group]) ? groups[group] : [];
      motions.forEach((motion) => {
        if (motion && Object.prototype.hasOwnProperty.call(motion, "sound")) {
          delete motion.sound;
        }
      });
    });
  }

  window.L2Dwidget.startMotion = function (group, index) {
    const model = readyModel();
    if (!model) return false;
    const groupName = String(group || "");
    const motionIndex = Number(index);
    const count = model.modelSetting.getMotionNum(groupName);
    if (!Number.isInteger(motionIndex) || motionIndex < 0 || motionIndex >= count) return false;
    muteMotionSounds(model);
    model.startMotion(groupName, motionIndex, 3); // PRIORITY_FORCE
    return true;
  };

  window.L2Dwidget.stopMotion = function () {
    const model = readyModel();
    if (!model || !model.mainMotionManager) return false;
    model.mainMotionManager.stopAllMotions();
    return true;
  };

  window.L2Dwidget.motionReady = function () {
    return !!readyModel();
  };
})();
