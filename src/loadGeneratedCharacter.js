import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
export async function loadGeneratedCharacter(scene,url='/models/field-commander.glb') {
  const gltf=await new GLTFLoader().loadAsync(url),model=gltf.scene; model.name='SF3D Field Commander';
  const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3()),scale=5/Math.max(size.y,1e-6);
  model.scale.setScalar(scale); model.position.set(-center.x*scale,-bounds.min.y*scale,-center.z*scale);
  model.traverse(node=>{if(!node.isMesh)return;node.castShadow=node.receiveShadow=true;if(node.material?.map)node.material.map.colorSpace=THREE.SRGBColorSpace});
  scene.add(model); return {model,animations:gltf.animations};
}
